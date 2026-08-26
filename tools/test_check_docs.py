import tempfile
import unittest
from pathlib import Path

from check_docs import check_archived_references, check_local_links, check_status_matrix


class DocumentationCheckerTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_valid_link_and_code_block_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/README.md", "[target](target.md)\n")
            self.write(root, "docs/target.md", "# Target\n")
            self.write(root, "docs/example.md", "```text\n[missing](missing.md)\n```\n")
            self.assertEqual(check_local_links(root), [])

    def test_broken_local_link_reports_file_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/README.md", "[missing](missing.md)\n")
            errors = check_local_links(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("docs/README.md:1", errors[0])
            self.assertIn("missing.md", errors[0])

    def test_status_matrix_requires_columns_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/status-matrix.md", "# Status\n\n| ID | 状态 |\n| --- | --- |\n")
            errors = check_status_matrix(root)
            self.assertTrue(any("expected columns" in error for error in errors))

    def test_archived_document_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "deprecated/20260101/docs/old.md", "# Old\n")
            self.write(root, "docs/README.md", "旧文档 old.md\n")
            errors = check_archived_references(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("old.md", errors[0])

    def test_runtime_dependency_readme_is_not_treated_as_product_doc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "deprecated/20260101/profile/node_modules/pkg/README.md", "# Dependency\n")
            self.write(root, "docs/README.md", "README.md is a normal filename\n")
            self.assertEqual(check_archived_references(root), [])


if __name__ == "__main__":
    unittest.main()
