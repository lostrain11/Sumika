from __future__ import annotations

import unittest

import quality_routing
from quality_routing.privacy import looks_like_secret_text as sdk_secret_detector
from sumika_core.browser.policy import looks_like_secret_text as browser_secret_detector
from sumika_core.quality import selection as sumika_selection


class QualitySelectionSdkCompatibilityTests(unittest.TestCase):
    def test_sumika_reexports_the_sdk_selection_core(self):
        for name in (
            "FixedEvaluationSample",
            "QualityPrior",
            "SelectionCohort",
            "SelectionEvidenceStore",
            "qualify_candidate",
            "resolve_binding",
        ):
            self.assertIs(getattr(sumika_selection, name), getattr(quality_routing, name))

    def test_browser_and_selection_share_the_same_secret_detector(self):
        self.assertIs(browser_secret_detector, sdk_secret_detector)
        self.assertTrue(browser_secret_detector("api_key=hidden-value"))


if __name__ == "__main__":
    unittest.main()

