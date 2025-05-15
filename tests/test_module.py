
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.transaction import Transaction
from trytond.pool import Pool


class MassEditingTestCase(ModuleTestCase):
    'Test MassEditing module'
    module = 'mass_editing'
    extras = ['party']

    @with_transaction()
    def test_mass_editing(self):
        "Test check erase of party"
        pool = Pool()
        MassEdit = pool.get('mass.editing')
        MassEditingWizard = pool.get('mass.editing.wizard', type='wizard')
        Party = pool.get('party.party')
        Model = pool.get('ir.model')
        ModelField = pool.get('ir.model.field')

        model_party, = Model.search([
            ('name', '=', 'party.party'),
            ], limit=1)
        field_name, = ModelField.search([
            ('name', '=', 'name'),
            ('model', '=', 'party.party'),
            ], limit=1)

        massedit = MassEdit()
        massedit.model = model_party
        massedit.model_fields = [field_name]
        massedit.save()
        MassEdit.create_keyword([massedit])
        self.assertTrue(massedit.keyword.id)

        party1 = Party()
        party1.name = 'John'
        party1.save()
        party2 = Party()
        party2.name = 'Julia'
        party2.save()

        self.assertTrue(len(set([party.name for party in Party.search([])])), 2)

        with Transaction().set_context(
                active_model='party.party',
                active_ids=[party1, party2],
                ):
            session_id, _, _ = MassEditingWizard.create()
            masseditig = MassEditingWizard(session_id)
            masseditig.start.selection_name = 'set'
            masseditig.start.name = 'Pepe'
            masseditig.transition_update()

        self.assertTrue(len(set([party.name for party in Party.search([])])), 1)

del ModuleTestCase
