
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from main import sync_once


class SyncOnceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.local_folder = self.temp_dir.name
        self.cloud = Mock()

    def create_file(self, name, content):
        path = os.path.join(self.local_folder, name)
        with open(path, "wb") as file_obj:
            file_obj.write(content)
        return path

    @patch("main.logger")
    def test_new_local_file_is_uploaded(self, logger):
        path = self.create_file("new.txt", b"hello")
        self.cloud.get_info.return_value = {}

        with patch("main.os.path.getsize", return_value=5):
            sync_once(self.cloud, self.local_folder)

        self.cloud.load.assert_called_once_with(path)
        self.cloud.reload.assert_not_called()
        self.cloud.delete.assert_not_called()

    @patch("main.logger")
    def test_changed_file_is_reloaded(self, logger):
        path = self.create_file("existing.txt", b"new content")
        self.cloud.get_info.return_value = {
            "existing.txt": {"md5": "different-hash", "size": 5}
        }
        self.cloud._file_md5.return_value = "local-hash"

        sync_once(self.cloud, self.local_folder)

        self.cloud.reload.assert_called_once_with(path)
        self.cloud.load.assert_not_called()

    @patch("main.logger")
    def test_missing_local_file_is_deleted_from_cloud(self, logger):
        self.cloud.get_info.return_value = {
            "deleted.txt": {"md5": "abc", "size": 3}
        }

        sync_once(self.cloud, self.local_folder)

        self.cloud.delete.assert_called_once_with("deleted.txt")
        self.cloud.load.assert_not_called()
        self.cloud.reload.assert_not_called()

    @patch("main.logger")
    def test_unchanged_file_is_not_uploaded_again(self, logger):
        self.create_file("same.txt", b"same")
        self.cloud.get_info.return_value = {
            "same.txt": {"md5": "same-hash", "size": 4}
        }
        self.cloud._file_md5.return_value = "same-hash"

        sync_once(self.cloud, self.local_folder)

        self.cloud.load.assert_not_called()
        self.cloud.reload.assert_not_called()
        self.cloud.delete.assert_not_called()

    @patch("main.logger")
    def test_cloud_listing_error_does_not_crash(self, logger):
        self.cloud.get_info.side_effect = RuntimeError("API unavailable")

        sync_once(self.cloud, self.local_folder)

        self.cloud.load.assert_not_called()
        self.cloud.reload.assert_not_called()
        self.cloud.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
