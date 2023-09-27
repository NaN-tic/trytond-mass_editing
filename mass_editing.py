# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from lxml import etree
import json

from trytond.transaction import Transaction
from trytond.pool import Pool
from trytond.wizard import Wizard, StateView, StateTransition, Button
from trytond.model import ModelView, ModelSQL, fields, Unique
from trytond.pyson import Eval, PYSONEncoder
from trytond.i18n import gettext
from trytond.exceptions import UserError

PAGE_FIELDS = 8


class MassEdit(ModelSQL, ModelView):
    'Mass Edit'
    __name__ = 'mass.editing'
    model = fields.Many2One('ir.model', 'Model', required=True,
        ondelete='CASCADE')
    model_fields = fields.Many2Many('mass.editing-ir.model.field',
        'mass_edit', 'field', 'Fields',
        domain=[
            ('model', '=', Eval('model', 0)),
            ],
        depends=['model'], order=[('field.field_description', 'ASC')])
    keyword = fields.Many2One('ir.action.keyword', 'Keyword', readonly=True)

    @classmethod
    def __setup__(cls):
        super(MassEdit, cls).__setup__()
        t = cls.__table__()
        cls._sql_constraints += [
            ('model_uniq', Unique(t, t.model),
             'Mass Edit must be unique per model.')
        ]
        cls._buttons.update({
                'create_keyword': {
                    'invisible': Eval('keyword'),
                    },
                'remove_keyword': {
                    'invisible': ~Eval('keyword'),
                    },
                })

    @classmethod
    def validate(cls, massedits):
        super(MassEdit, cls).validate(massedits)
        for massedit in massedits:
            Model = Pool().get(massedit.model.model)
            if not issubclass(Model, ModelSQL):
                raise UserError(gettext('massedit.not_modelsql',
                    model=massedit.rec_name))

    def get_rec_name(self, name):
        return '%s' % (self.model.rec_name)

    @classmethod
    @ModelView.button
    def create_keyword(cls, massedits):
        pool = Pool()
        Action = pool.get('ir.action.wizard')
        ModelData = pool.get('ir.model.data')
        Keyword = pool.get('ir.action.keyword')

        for massedit in massedits:
            if massedit.keyword:
                continue
            action = Action(ModelData.get_id('mass_editing',
                    'wizard_mass_editing'))
            keyword = Keyword()
            keyword.keyword = 'form_action'
            keyword.model = '%s,-1' % massedit.model.model
            keyword.action = action.action
            keyword.save()
            massedit.keyword = keyword
            massedit.save()

    @classmethod
    @ModelView.button
    def remove_keyword(cls, massedits):
        pool = Pool()
        Keyword = pool.get('ir.action.keyword')
        Keyword.delete([x.keyword for x in massedits if x.keyword])

    @classmethod
    def delete(cls, massedits):
        cls.remove_keyword(massedits)
        super(MassEdit, cls).delete(massedits)


class MassEditFields(ModelSQL):
    'Mass Edit Fields'
    __name__ = 'mass.editing-ir.model.field'

    mass_edit = fields.Many2One('mass.editing', 'Mass', required=True,
        ondelete='CASCADE')
    field = fields.Many2One('ir.model.field', 'Field', required=True,
        ondelete='CASCADE')


class MassEditWizardStart(ModelView):
    'Mass Edit Wizard Start'
    __name__ = 'mass.editing.wizard.start'

    @classmethod
    def __setup__(cls):
        super(MassEditWizardStart, cls).__setup__()

    @classmethod
    def fields_view_get(cls, view_id=None, view_type='form', level=None):
        class Decoder(json.JSONDecoder):

            def __init__(self, context=None):
                self.__context = context or {}
                super(Decoder, self).__init__(object_hook=self._object_hook)

            def _object_hook(self, dct):
                if '__class__' in dct:
                    return 'REMOVE_CLAUSE'
                return dct

        pool = Pool()
        MassEdit = pool.get('mass.editing')
        Field = pool.get('ir.model.field')

        res = super(MassEditWizardStart, cls).fields_view_get(view_id,
            view_type, level)

        if view_type == 'tree':
            return res

        context = Transaction().context
        model = context.get('active_model', None)
        if not model:
            return res
        EditingModel = pool.get(model)

        edits = MassEdit.search([('model.model', '=', model)], limit=1)
        if not edits:
            return res
        edit, = edits
        fields = res['fields']
        root = etree.fromstring(res['arch'])
        # Iterate on all root children and remove them except for the tag
        # separator with id attribute = 'fields'
        for child in root.getchildren():
            if (child.tag == 'separator' and child.get('id') == 'fields'):
                continue
            root.remove(child)

        form = root.find('separator').getparent()
        Model = pool.get(edit.model.model)

        model_fields = edit.model_fields
        company_field = None
        if hasattr(Model, 'company'):
            if not [f for f in edit.model_fields
                    if f.name == 'company' and f.ttype == 'many2one']:
                company_field = Field.search([
                    ('name', '=', 'company'),
                    ('model.model', '=', model)], limit=1)
                if company_field:
                    model_fields = model_fields + (company_field[0],)

        model_field_names = [f.name for f in model_fields]
        for k, v in EditingModel.fields_get(model_field_names).items():
            # Ensure field_name key from fields_get is requested in edit.model_fields
            if k in model_field_names:
                fields[k] = v

        # Add notebook if many fields
        pages = []
        if len(model_fields) > PAGE_FIELDS:
            field_string = MassEdit.fields_get(['model_fields']
                )['model_fields']['string']
            notebook = etree.SubElement(form, 'notebook', {})
            for x in range(0, ((len(model_fields)-1) // PAGE_FIELDS) + 1):
                if x == 0:
                    first = 'A'
                else:
                    first = model_fields[x * PAGE_FIELDS].field_description[0]
                idx = (x + 1) * PAGE_FIELDS - 1
                if idx < len(model_fields) - 1:
                    last = model_fields[idx].field_description[0]
                else:
                    last = 'Z'
                pages.append(etree.SubElement(notebook, 'page', {
                        'string': '%s (%s-%s)' % (field_string, first.upper(),
                            last.upper()),
                        'id': 'page_%s' % x,
                }))

        for index, field in enumerate(model_fields):
            if fields[field.name].get('states'):
                fields[field.name]['states'] = {}

            if fields[field.name].get('required'):
                fields[field.name]['required'] = False

            if fields[field.name].get('on_change'):
                fields[field.name]['on_change'] = []
            if fields[field.name].get('on_change_with'):
                fields[field.name]['on_change_with'] = []

            if fields[field.name].get('domain'):
                old_domain = Decoder().decode(fields[field.name]['domain'])
                new_domain = []
                for clause in old_domain:
                    if 'REMOVE_CLAUSE' not in str(clause):
                        new_domain.append(clause)
                fields[field.name]['domain'] = \
                    PYSONEncoder().encode(new_domain)

            if field.ttype in ['many2many', 'one2many']:
                selection_vals = [
                    ('', ''),
                    ('set', 'Set'),
                    ('remove_all', 'Remove All'),
                    ]
                _field = getattr(EditingModel, field.name, None)
                if field.ttype == 'many2many' or _field.add_remove:
                    selection_vals.append(('add', 'Add'),)
                    selection_vals.append(('remove', 'Remove'),)

                if fields[field.name].get('add_remove'):
                    del fields[field.name]['add_remove']
            elif field.ttype == 'selection':
                field_selection = getattr(EditingModel, field.name).selection
                if isinstance(field_selection, str):
                    selection = getattr(EditingModel, field_selection)()
                    fields[field.name]['selection'] = selection
            else:
                selection_vals = [
                    ('', ''),
                    ('set', 'Set'),
                    ('remove', 'Remove')
                ]
            translated_vals = []
            for val in selection_vals:
                if val[0]:
                    translated_vals.append((val[0], gettext('mass_editing.%s' %
                                val[0])))
                else:
                    translated_vals.append((val[0], ''))

            colspan = '1'
            if field.ttype in ['many2many', 'one2many']:
                colspan = '2'

            fields['selection_%s' % field.name] = {
                'name': 'selection_%s' % field.name,
                'type': 'selection',
                'string': fields[field.name]['string'],
                'selection': translated_vals,
                'help': '',
                }

            xml_parent = form if not pages else pages[index // PAGE_FIELDS]
            xml_group = etree.SubElement(xml_parent, 'group', {
                    'col': '2',
                    'colspan': '4',
                    })

            if field.name == 'company' and company_field:
                etree.SubElement(form, 'field', {
                    'name': 'company',
                    'colspan': '2',
                    'readonly': '1',
                    'invisible': '1',
                    })
                continue

            to_find = ".//label[@id='label_%s']" % field.name
            if root.find(to_find) is None:
                etree.SubElement(xml_group, 'label', {
                        'id': "label_%s" % field.name,
                        'string': fields[field.name]['string'],
                        'xalign': '0.0',
                        'colspan': '4',
                        })
            to_find = ".//field[@name='selection_%s']" % field.name
            if root.find(to_find) is None:
                etree.SubElement(xml_group, 'field', {
                        'name': "selection_%s" % field.name,
                        'colspan': colspan,
                        })
            to_find = ".//field[@name='%s']" % field.name
            if root.find(to_find) is None:
                etree.SubElement(xml_group, 'field', {
                        'name': field.name,
                        'colspan': colspan,
                        })

        res['arch'] = etree.tostring(root).decode('utf-8')
        res['fields'] = fields
        return res

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        context = Transaction().context
        res = dict.fromkeys([f for f in fields if f[:10] == 'selection_'], '')
        model = context.get('active_model')
        if model:
            EditingModel = pool.get(model)
            res.update(EditingModel.default_get([f for f in fields
                        if f[:10] != 'selection_'], with_rec_name))
        return res


class CustomDict(dict):

    def __getattr__(self, name):
        return {}

    def __setattr__(self, name, value):
        self[name] = value


class MassEditingWizard(Wizard):
    'Mass Edit Wizard'
    __name__ = 'mass.editing.wizard'
    start = StateView('mass.editing.wizard.start',
          'mass_editing.view_mass_editing_wizard_start', [
                Button('Cancel', 'end', 'tryton-cancel'),
                Button('Apply', 'update', 'tryton-ok', True),
                ])

    update = StateTransition()

    def __getattribute__(self, name):
        if name == 'start':
            if not hasattr(self, 'start_data'):
                self.start_data = CustomDict()
            name = 'start_data'
        return super(MassEditingWizard, self).__getattribute__(name)

    def transition_update(self):
        pool = Pool()
        context = Transaction().context

        res = {}
        model = context.get('active_model')
        if not model:
            return 'end'
        EditingModel = pool.get(model)
        vals = self.start_data
        for field, value in vals.items():
            if field.startswith('selection_'):
                split_key = field.split('_', 1)[1]
                _field = getattr(EditingModel, split_key, None)
                xxx2many = False
                one2many = False
                dik = False
                if isinstance(_field, fields.Function) and _field.setter:
                    _field = _field._field  # Use original field
                if (isinstance(_field, fields.One2Many)
                        or isinstance(_field, fields.Many2Many)):
                    xxx2many = True
                if (isinstance(_field, fields.Dict)):
                    dik = True

                if isinstance(_field, fields.One2Many):
                    one2many = True
                if value == 'set':
                    if xxx2many:
                        manyvals = vals.get(split_key, None)
                        to_set = []
                        to_create = []
                        for val in manyvals:
                            if isinstance(val, dict):
                                # check_xxx2many
                                TargetModel = pool.get(_field.model_name)

                                new_val = val.copy()
                                for field_name, field_value in val.items():
                                    if isinstance(field_value, list):
                                        new_val[field_name] = [tuple(['add',
                                                field_value])]
                                    target_field = TargetModel._fields[
                                        field_name]
                                    if (isinstance(
                                                target_field, fields.Function)
                                            and not target_field.setter):
                                        del new_val[field_name]

                                to_create.append(new_val)
                            else:
                                to_set.append(val)
                        to_write = []
                        if to_set:
                            xxx2m_ids = set()
                            records = EditingModel.search([
                                ('id', 'in',
                                    Transaction().context.get('active_ids')),
                                ])
                            for record in records:
                                xxx2m_ids |= set([r.id for r in getattr(
                                    record, _field.name)])
                            xxx2m_ids = list(
                                xxx2m_ids - set(to_set) - set(to_create))
                            to_write.append(('remove', xxx2m_ids))
                            to_write.append(('add', to_set))
                        if to_create:
                            to_write.append(('create', to_create),)
                        if to_write:
                            res.update({split_key: to_write})
                    else:
                        if not dik:
                            res.update({split_key: vals.get(split_key, None)})
                        else:
                            records = EditingModel.browse(Transaction().context.get('active_ids'))
                            for record in records:
                                val = dict(getattr(record, split_key) or {})
                                val.update(vals.get(split_key))
                                setattr(
                                    record,
                                    split_key,
                                    val)
                                record.save()

                elif value == 'remove':
                    if xxx2many:
                        res.update({split_key: [
                                    ("remove", vals.get(split_key, []))
                                    ]})
                    else:
                        res.update({split_key: None})
                elif value == 'remove_all':
                    xxx2m_ids = set()
                    records = EditingModel.search([
                        ('id', 'in', Transaction().context.get('active_ids'))])
                    for record in records:
                        xxx2m_ids |= set([r.id for r in getattr(
                            record, _field.name)])
                    res.update({split_key: [
                                ('delete' if one2many else 'remove',
                                    list(xxx2m_ids))]})
                elif value == 'add':
                    res.update({split_key: [('add', vals.get(split_key, []))]})
        if res:
            instances = EditingModel.browse(Transaction().context.get(
                    'active_ids'))
            EditingModel.write(instances, res)
        return 'end'
