"""Published receipt examples match the schema and say they are provisional."""

import glob
import json
import os
import unittest

from helpers import ROOT
from schema_check import errors, load_schema


class Examples(unittest.TestCase):
    def test_examples_validate_and_are_labeled(self):
        paths = sorted(glob.glob(os.path.join(ROOT, "examples", "*.json")))
        self.assertTrue(paths)
        schema = load_schema()
        for path in paths:
            with self.subTest(path=os.path.basename(path)):
                with open(path) as handle:
                    receipt = json.load(handle)
                self.assertEqual(errors(receipt, schema), [])
                self.assertTrue(receipt["_provenance"].startswith("provisional, non-authoritative"))
                self.assertEqual(receipt["contract"]["status"], "pending")

    def test_validator_rejects_a_bad_receipt(self):
        path = os.path.join(ROOT, "examples", "launch-receipt.partial.provisional.json")
        with open(path) as handle:
            receipt = json.load(handle)
        receipt["sessions"][0]["state"] = "finished"
        del receipt["failure"]
        problems = errors(receipt, load_schema())
        self.assertIn("$: missing failure", problems)
        self.assertTrue(any("'finished' not in" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
