import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Adjust path to import from api
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'api'))

# Pop NO_PROXY to avoid httpx parse issues locally
os.environ.pop('NO_PROXY', None)

import dotenv
dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'api', '.env'))

import storage_client
import project_manager

class TestResumeLossFixes(unittest.TestCase):

    def test_list_files_pagination_mocked(self):
        """Test list_files pagination behaves correctly across pages."""
        mock_sb = MagicMock()
        mock_bucket = MagicMock()
        mock_sb.storage.from_.return_value = mock_bucket

        # Set up a mock return value for list() which returns 100 items first, then 50 items
        page_1 = [{"name": f"file_{i}.txt", "id": f"id_{i}"} for i in range(100)]
        page_2 = [{"name": f"file_{i}.txt", "id": f"id_{i}"} for i in range(100, 150)]

        # The mock list() should return page_1, then page_2
        mock_bucket.list.side_effect = [page_1, page_2]

        with patch('storage_client.get_supabase', return_value=mock_sb):
            res = storage_client.list_files("dummy-prefix/")
            self.assertEqual(len(res), 150)
            self.assertEqual(mock_bucket.list.call_count, 2)
            
            # Verify the limit and offset passed to options
            args_call_1 = mock_bucket.list.call_args_list[0]
            self.assertEqual(args_call_1[0][0], "dummy-prefix/")
            self.assertEqual(args_call_1[0][1]["limit"], 100)
            self.assertEqual(args_call_1[0][1]["offset"], 0)

            args_call_2 = mock_bucket.list.call_args_list[1]
            self.assertEqual(args_call_2[0][0], "dummy-prefix/")
            self.assertEqual(args_call_2[0][1]["limit"], 100)
            self.assertEqual(args_call_2[0][1]["offset"], 100)

    def test_list_projects_db_priority(self):
        """Test list_projects queries the database projects table first."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table

        # Return mock database rows
        mock_db_data = [
            {"name": "project_alpha", "created_at": "2026-06-21T10:00:00Z", "pdf_storage_path": "/path/alpha"},
            {"name": "project_beta", "created_at": "2026-06-21T09:00:00Z", "pdf_storage_path": "/path/beta"}
        ]
        
        # mock supabase select/execute chain
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.order.return_value = mock_table
        
        mock_res = MagicMock()
        mock_res.data = mock_db_data
        mock_table.execute.return_value = mock_res

        with patch('supabase_client.get_supabase', return_value=mock_sb):
            # Patch step_output_exists to prevent storage network requests during test
            with patch('project_manager.step_output_exists', return_value=False):
                with patch('project_manager.Path.exists', return_value=False):
                    projects = project_manager.list_projects("admin")
                    self.assertEqual(len(projects), 2)
                    self.assertEqual(projects[0]["name"], "project_alpha")
                    self.assertEqual(projects[0]["last_modified"], "2026-06-21T10:00:00Z")
                    self.assertEqual(projects[1]["name"], "project_beta")
                    self.assertEqual(projects[1]["last_modified"], "2026-06-21T09:00:00Z")

    def test_create_project_db_upsert(self):
        """Test that create_project registers the project in the projects DB table."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        
        # mock user dict
        user = {"id": "admin", "email": "admin@example.com"}

        # Configure mock chains
        mock_table.upsert.return_value = mock_table

        with patch('real_api.get_supabase', return_value=mock_sb):
            with patch('real_api._get_user_db_id', return_value="admin-uuid"):
                with patch('real_api.get_or_create'):
                    with patch('real_api.Path.write_text'):
                        with patch('real_api.write_file'):
                            with patch('real_api.Path.mkdir'):
                                import real_api
                                real_api.create_project({"name": "test_project", "pdf_path": "/pdf"}, user=user)
                                
                                # Verify upsert was called with the correct args
                                mock_sb.table.assert_called_with("projects")
                                mock_table.upsert.assert_called_with({
                                    "user_id": "admin-uuid",
                                    "name": "test_project",
                                    "pdf_storage_path": "/pdf"
                                }, on_conflict="user_id,name")

    def test_delete_project_db_delete(self):
        """Test that delete_project removes the project from the projects DB table."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table

        # Configure mock chains
        mock_table.delete.return_value = mock_table
        mock_table.eq.return_value = mock_table

        # mock user dict
        user = {"id": "admin", "email": "admin@example.com"}

        with patch('real_api.get_supabase', return_value=mock_sb):
            with patch('real_api._get_user_db_id', return_value="admin-uuid"):
                with patch('real_api.file_exists', return_value=True):
                    with patch('real_api.delete_prefix'):
                        with patch('real_api.shutil.rmtree'):
                            with patch('real_api.Path.exists', return_value=True):
                                import real_api
                                real_api.delete_project("test_project", user=user)
                                
                                # Verify delete chain was called with the correct args
                                mock_sb.table.assert_called_with("projects")
                                mock_table.delete.assert_called_once()
                                mock_table.eq.assert_any_call("user_id", "admin-uuid")
                                mock_table.eq.assert_any_call("name", "test_project")

if __name__ == "__main__":
    unittest.main()
