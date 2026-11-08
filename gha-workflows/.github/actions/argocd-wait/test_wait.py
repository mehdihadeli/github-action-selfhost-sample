import copy
import unittest

import wait


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.application = {
            'status': {
                'sync': {'revision': 'promoted', 'status': 'Synced'},
                'health': {'status': 'Healthy'},
                'summary': {'images': ['verified-image']},
            },
        }

    def test_should_accept_exact_revision_image_and_health(self):
        self.assertTrue(wait.is_ready(self.application, 'promoted', 'verified-image'))

    def test_should_reject_previous_healthy_revision(self):
        self.assertFalse(wait.is_ready(self.application, 'new-commit', 'verified-image'))

    def test_should_reject_wrong_image_at_current_revision(self):
        self.assertFalse(wait.is_ready(self.application, 'promoted', 'different-image'))

    def test_should_reject_degraded_health(self):
        state = copy.deepcopy(self.application)
        state['status']['health']['status'] = 'Degraded'
        self.assertFalse(wait.is_ready(state, 'promoted', 'verified-image'))

    def test_should_reject_out_of_sync_desired_state(self):
        state = copy.deepcopy(self.application)
        state['status']['sync']['status'] = 'OutOfSync'
        self.assertFalse(wait.is_ready(state, 'promoted', 'verified-image'))

    def test_should_reject_absent_reconciliation_state(self):
        self.assertFalse(wait.is_ready({}, 'promoted', 'verified-image'))


if __name__ == '__main__':
    unittest.main()