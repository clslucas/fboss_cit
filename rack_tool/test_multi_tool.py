import unittest
from unittest.mock import patch, MagicMock, call, mock_open
import os

# Add the script's directory to the path to allow importing multi_tool
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from multi_tool import RemoteOperation, Colors

class TestRemoteOperation(unittest.TestCase):

    def setUp(self):
        """Set up a test instance of RemoteOperation."""
        self.op = RemoteOperation('testhost', 'testuser', 'testpass')

    @patch('multi_tool.paramiko.SSHClient')
    def test_execute_command_success(self, mock_ssh_client):
        """Test successful command execution."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance

        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ['output line 1\n', '']
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_stderr = MagicMock()
        mock_stderr.readline.side_effect = ['']

        mock_client_instance.exec_command.return_value = (None, mock_stdout, mock_stderr)

        # Execute
        success, host, output, status_msg = self.op.execute_command('ls -l')

        # Assert
        self.assertTrue(success)
        self.assertEqual(host, 'testhost')
        self.assertIn('output line 1', output)
        self.assertIn('SUCCESS', status_msg)
        mock_client_instance.connect.assert_called_once_with(
            hostname='testhost', username='testuser', password='testpass', timeout=10,
            allow_agent=False, look_for_keys=False
        )
        mock_client_instance.exec_command.assert_called_once_with('ls -l', timeout=None)
        mock_client_instance.close.assert_called_once()

    @patch('multi_tool.paramiko.SSHClient')
    def test_execute_command_failure_exit_code(self, mock_ssh_client):
        """Test command execution failure due to non-zero exit code."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance

        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ['']
        mock_stdout.channel.recv_exit_status.return_value = 1

        mock_stderr = MagicMock()
        mock_stderr.readline.side_effect = ['error line\n', '']

        mock_client_instance.exec_command.return_value = (None, mock_stdout, mock_stderr)

        # Execute
        success, host, output, status_msg = self.op.execute_command('bad-command')

        # Assert
        self.assertFalse(success)
        self.assertEqual(host, 'testhost')
        self.assertIn('error line', output)
        self.assertIn('FAILURE', status_msg)
        self.assertIn('exit code 1', status_msg)

    @patch('multi_tool.time.sleep')
    @patch('multi_tool.paramiko.SSHClient')
    def test_connection_retry_logic(self, mock_ssh_client, mock_sleep):
        """Test that connection is retried on failure."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance

        # Fail first two times, succeed on the third
        mock_client_instance.connect.side_effect = [Exception("Connection failed"), Exception("Still failed"), None]

        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ['ok\n', '']
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_client_instance.exec_command.return_value = (None, mock_stdout, MagicMock())

        # Execute
        success, _, _, _ = self.op.execute_command('uptime')

        # Assert
        self.assertTrue(success)
        self.assertEqual(mock_client_instance.connect.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch('multi_tool.paramiko.SSHClient')
    def test_connection_final_failure(self, mock_ssh_client):
        """Test that it fails after all retries are exhausted."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance
        mock_client_instance.connect.side_effect = Exception("Permanent failure")

        # Execute
        success, host, output, status_msg = self.op.execute_command('uptime')

        # Assert
        self.assertFalse(success)
        self.assertEqual(host, 'testhost')
        self.assertIn('FAILURE', status_msg)
        self.assertIn('Permanent failure', status_msg)
        # Should be called CONNECTION_RETRIES times (default 3)
        self.assertEqual(mock_client_instance.connect.call_count, 3)

    @patch('multi_tool.paramiko.SSHClient')
    def test_transfer_file_success(self, mock_ssh_client):
        """Test successful file transfer."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_sftp_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance
        mock_client_instance.open_sftp.return_value.__enter__.return_value = mock_sftp_instance

        # Execute
        success, host, status_msg = self.op.transfer_file('/local/path/file.txt', '/remote/path')

        # Assert
        self.assertTrue(success)
        self.assertEqual(host, 'testhost')
        self.assertIn('SUCCESS', status_msg)
        mock_sftp_instance.put.assert_called_once_with('/local/path/file.txt', '/remote/path/file.txt')
        mock_client_instance.close.assert_called_once()

    @patch('multi_tool.paramiko.SSHClient')
    def test_transfer_file_failure(self, mock_ssh_client):
        """Test file transfer failure during SFTP put."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_sftp_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance
        mock_client_instance.open_sftp.return_value.__enter__.return_value = mock_sftp_instance
        mock_sftp_instance.put.side_effect = IOError("Permission denied")

        # Execute
        success, host, status_msg = self.op.transfer_file('/local/path/file.txt', '/remote/path')

        # Assert
        self.assertFalse(success)
        self.assertEqual(host, 'testhost')
        self.assertIn('FAILURE', status_msg)
        self.assertIn('Permission denied', status_msg)

    @patch('builtins.open', new_callable=mock_open)
    @patch('multi_tool.os.path.join')
    @patch('multi_tool.paramiko.SSHClient')
    def test_logging_is_called(self, mock_ssh_client, mock_path_join, mock_open_builtin):
        """Test that logging to a file works as expected."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_ssh_client.return_value = mock_client_instance

        mock_stdout = MagicMock()
        mock_stdout.readline.side_effect = ['log content\n', '']
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_client_instance.exec_command.return_value = (None, mock_stdout, MagicMock())

        log_dir = '/tmp/logs'
        log_path = os.path.join(log_dir, 'testhost.log')
        mock_path_join.return_value = log_path

        # Execute
        self.op.execute_command('echo "hello"', log_dir=log_dir)

        # Assert
        mock_path_join.assert_called_once_with(log_dir, 'testhost.log')
        mock_open_builtin.assert_called_once_with(log_path, 'w')
        handle = mock_open_builtin()
        handle.write.assert_any_call('--- Command: echo "hello" ---\n')
        handle.writelines.assert_called_once_with(['log content\n'])

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)