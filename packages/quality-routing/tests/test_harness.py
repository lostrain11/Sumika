import json
from pathlib import Path
import subprocess
import sys
import unittest
from dataclasses import MISSING, FrozenInstanceError, fields, replace

from quality_routing.contracts import RoutingError
from quality_routing.harness import (
    CapabilityEvidence, ExternalSessionRef, InvocationReceipt, MergePreview,
    ModelInvocation, RecoveryAssessment, RuntimeBinding,
)


class HarnessTests(unittest.TestCase):
    def binding(self, **changes):
        return RuntimeBinding(**{ "harness_id": "fixture", "instance_id": "profile-one",
            "distribution_id": "release-one", "adapter_version": "1", "execution_mode": "managed",
            "identity_evidence_ref": "fixture-profile", "launch_id": "launch-one",
            "launch_evidence_ref": "fixture-launch", **changes})

    def test_versioned_roundtrip_and_closed_schema(self):
        binding = self.binding()
        self.assertEqual(RuntimeBinding.from_dict(binding.to_dict()), binding)
        for value in ({}, {**binding.to_dict(), "schema_version": "runtime-binding/v2"},
                      {**binding.to_dict(), "api_key": "secret"}):
            with self.assertRaises(RoutingError):
                RuntimeBinding.from_dict(value)
        with self.assertRaises(FrozenInstanceError):
            binding.instance_id = "changed"

    def test_launch_and_distribution_changes_never_match_running_attempt(self):
        binding = self.binding()
        self.assertTrue(binding.matches_attempt(self.binding()))
        for changes in ({"launch_id": "launch-two"}, {"instance_id": "profile-two"},
                        {"distribution_id": "release-two"}, {"adapter_version": "2"},
                        {"harness_id": "other"}, {"execution_mode": "external"}):
            self.assertFalse(binding.matches_attempt(self.binding(**changes)))
        unknown = self.binding(launch_id=None, launch_evidence_ref=None)
        self.assertFalse(unknown.matches_attempt(unknown))
        with self.assertRaises(RoutingError):
            self.binding(launch_evidence_ref=None)

    def test_session_identity_is_scoped_but_survives_known_restart(self):
        binding = self.binding()
        ref = ExternalSessionRef("fixture", "profile-one", "会话 with spaces:1", "turn-1")
        self.assertEqual(ExternalSessionRef.from_dict(ref.to_dict()), ref)
        self.assertTrue(ref.belongs_to(replace(binding, launch_id="launch-two")))
        self.assertNotEqual(ref.session_key, replace(ref, instance_id="profile-two").session_key)
        self.assertNotEqual(ref.session_key, replace(ref, harness_id="other").session_key)
        self.assertFalse(ref.belongs_to(replace(binding, instance_id="profile-two")))
        for value in (None, "", "bad\nref", "a" * 513):
            with self.assertRaises(RoutingError):
                replace(ref, session_id=value)

    def test_binding_contains_references_not_local_paths(self):
        with self.assertRaises(RoutingError):
            self.binding(identity_evidence_ref="D:/private/profile")

    def records(self):
        return (
            self.binding(),
            ExternalSessionRef("fixture", "profile-one", "会话 with spaces:1", "turn-1"),
            CapabilityEvidence("model-call", "supported", ("Only verified in fixture",), ("probe-1",)),
            ModelInvocation("work-1", 1, "operation-1", "Independent verification", "candidate-1",
                            self.binding(), "input-1", "aB" * 32, "limits-1"),
            InvocationReceipt("operation-1", self.binding(), "completed", "result-1", "usage-1",
                              "price-1", ("resource-1",), ("receipt-1",)),
            RecoveryAssessment("work-1", 1, self.binding(), ("operation-1",), ("inspect", "resume"),
                               ("recovery-1",), "Operations reconciled"),
            MergePreview("work-1", 1, "preview-1", "12" * 32, "changes-1", ("verification-1",),
                         self.binding()),
        )

    def test_all_records_roundtrip_through_json_and_are_immutable(self):
        for record in self.records():
            with self.subTest(record=type(record).__name__):
                encoded = record.to_dict()
                self.assertTrue(encoded["schema_version"].endswith("/v1"))
                restored = type(record).from_dict(json.loads(json.dumps(encoded)))
                self.assertEqual(restored, record)
                self.assertEqual(hash(restored), hash(record))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, fields(record)[0].name, "changed")
                for field in fields(record):
                    value = getattr(record, field.name)
                    if isinstance(value, tuple):
                        self.assertIsInstance(encoded[field.name], list)
                        self.assertIsInstance(getattr(restored, field.name), tuple)
                    if isinstance(value, RuntimeBinding):
                        self.assertEqual(encoded[field.name], value.to_dict())
                        self.assertIsInstance(getattr(restored, field.name), RuntimeBinding)

    def test_all_records_reject_unknown_schema_fields_and_missing_required_fields(self):
        for record in self.records():
            encoded = record.to_dict()
            invalid = [None, [], "record", {},
                       {**encoded, "schema_version": "unknown/v1"},
                       {**encoded, "schema_version": record.schema_version.replace("/v1", "/v2")}]
            for name in ("prompt", "tools", "credentials", "retry", "extra"):
                invalid.append({**encoded, name: "raw-value"})
            for field in fields(record):
                if field.default is MISSING and field.default_factory is MISSING:
                    invalid.append({key: value for key, value in encoded.items() if key != field.name})
            for value in invalid:
                with self.subTest(record=type(record).__name__, value=value):
                    with self.assertRaises(RoutingError):
                        type(record).from_dict(value)

    def test_nested_bindings_have_closed_versioned_schema(self):
        for record in self.records()[3:]:
            for binding in (None, {}, "binding", [], self.binding().to_dict() | {"schema_version": "runtime-binding/v2"},
                            self.binding().to_dict() | {"credentials": "secret"},
                            {key: value for key, value in self.binding().to_dict().items() if key != "instance_id"}):
                if binding is None and isinstance(record, (RecoveryAssessment, MergePreview)):
                    continue
                with self.subTest(record=type(record).__name__, binding=binding):
                    with self.assertRaises(RoutingError):
                        type(record).from_dict(record.to_dict() | {"runtime_binding": binding})
            for binding in ("binding", {}, [], True):
                with self.assertRaises(RoutingError):
                    replace(record, runtime_binding=binding)

    def test_positive_revisions_and_hex_digests_are_strict(self):
        for record in self.records():
            if hasattr(record, "requirement_revision"):
                for revision in (True, False, 0, -1, 1.0, "1", None, 10**9 + 1):
                    with self.subTest(record=type(record).__name__, revision=revision):
                        with self.assertRaises(RoutingError):
                            replace(record, requirement_revision=revision)
            for name in ("input_digest", "source_digest"):
                if hasattr(record, name):
                    for digest in (None, True, 64, [], "a" * 63, "a" * 65, "g" * 64, "a" * 63 + "\n"):
                        with self.assertRaises(RoutingError):
                            replace(record, **{name: digest})

    def test_references_are_identifiers_and_text_is_bounded(self):
        for record in self.records()[2:]:
            for field in fields(record):
                if field.name.endswith("_ref") or field.name.endswith("_id"):
                    for value in ("/private/input", "D:\\private\\input", "../input", "https://host/input",
                                  "raw prompt text", "", "a" * 241, {}, True, 1):
                        with self.subTest(record=type(record).__name__, field=field.name, value=value):
                            with self.assertRaises(RoutingError):
                                replace(record, **{field.name: value})
                if field.name in ("purpose", "reason", "limitations"):
                    for value in (None, 1, True, {}, "", " ", "bad\x00text", "a" * 24001):
                        with self.assertRaises(RoutingError):
                            replace(record, **{field.name: (value,) if field.name == "limitations" else value})

    def test_tuple_fields_reject_invalid_containers_and_copy_lists(self):
        for record in self.records()[2:]:
            for field in fields(record):
                original = getattr(record, field.name)
                if not isinstance(original, tuple):
                    continue
                values = list(original)
                copied = replace(record, **{field.name: values})
                values.append("mutated")
                self.assertEqual(getattr(copied, field.name), original)
                for value in (None, "reference", {}, {"reference"}, 1, True, ["reference"] * 129,
                              [None], [1], [True], [{}], [[]]):
                    with self.subTest(record=type(record).__name__, field=field.name, value=value):
                        with self.assertRaises(RoutingError):
                            replace(record, **{field.name: value})
                if field.name.endswith("_refs"):
                    for value in ("../private", "D:/private", "D:\\private", "/private", "a" * 241):
                        with self.assertRaises(RoutingError):
                            replace(record, **{field.name: (value,)})

    def test_capability_and_submission_facts(self):
        capability = self.records()[2]
        for status in ("supported", "unsupported", "unverified"):
            self.assertEqual(replace(capability, status=status).status, status)
        for status in (True, None, [], {}, "unknown", ""):
            with self.assertRaises(RoutingError):
                replace(capability, status=status)
        for submission in (True, None, [], {}, "failed", "cancelled", "retry"):
            with self.assertRaises(RoutingError):
                InvocationReceipt("operation-1", self.binding(), submission)
        with self.assertRaises(RoutingError):
            InvocationReceipt("operation-1", self.binding(), "completed")
        with self.assertRaises(RoutingError):
            InvocationReceipt("operation-1", self.binding(), "definitely-not-sent", "result-1")
        for submission in ("unknown", "definitely-not-sent"):
            receipt = InvocationReceipt("operation-1", self.binding(), submission)
            self.assertEqual(InvocationReceipt.from_dict(json.loads(json.dumps(receipt.to_dict()))), receipt)
            self.assertIsNone(receipt.result_ref)
            self.assertFalse(hasattr(receipt, "retry"))
        partial = InvocationReceipt("operation-1", self.binding(), "unknown", "partial-result-1")
        self.assertEqual(partial.submission, "unknown")

    def test_resume_requires_launch_evidence_and_resolved_operations(self):
        assessment = self.records()[5]
        for changes in ({"runtime_binding": None},
                        {"runtime_binding": self.binding(launch_id=None, launch_evidence_ref=None)},
                        {"evidence_refs": ()}, {"unresolved_operation_ids": ("operation-1",)},
                        {"unresolved_operation_ids": ("other-operation",)},
                        {"allowed_actions": ("retry",)}):
            with self.assertRaises(RoutingError):
                replace(assessment, **changes)
        for binding in (None, self.binding(launch_id=None, launch_evidence_ref=None)):
            readonly = replace(assessment, runtime_binding=binding, allowed_actions=("inspect", "reconcile"),
                               evidence_refs=(), unresolved_operation_ids=("operation-1",))
            self.assertEqual(RecoveryAssessment.from_dict(json.loads(json.dumps(readonly.to_dict()))), readonly)
        legacy = assessment.to_dict()
        del legacy["unresolved_operation_ids"]
        self.assertEqual(RecoveryAssessment.from_dict(legacy).unresolved_operation_ids, ())
        preview = replace(self.records()[6], runtime_binding=None)
        self.assertEqual(MergePreview.from_dict(json.loads(json.dumps(preview.to_dict()))), preview)

    def test_contracts_import_without_sumika_dependencies(self):
        source = Path(__file__).resolve().parents[1] / "src"
        script = """
import importlib.abc
import sys

class RejectSumika(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('sumika'):
            raise AssertionError('Sumika dependency: ' + fullname)

sys.meta_path.insert(0, RejectSumika())
sys.path.insert(0, sys.argv[1])
from quality_routing.harness import *
assert CapabilityEvidence.from_dict(CapabilityEvidence('probe', 'unverified', (), ()).to_dict())
assert not any(name.startswith('sumika') for name in sys.modules)
"""
        result = subprocess.run([sys.executable, "-I", "-c", script, str(source)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
