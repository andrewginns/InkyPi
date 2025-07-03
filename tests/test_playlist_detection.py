import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from model import Playlist, PlaylistManager, PluginInstance


class TestPlaylistDetection(unittest.TestCase):
    """Comprehensive tests for playlist active detection edge cases."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.manager = PlaylistManager()
        
    def create_plugin(self, plugin_id="test_plugin", name="Test Plugin"):
        """Helper to create a mock plugin instance."""
        return PluginInstance(
            plugin_id=plugin_id,
            name=name,
            settings={},
            refresh={"interval": 3600}
        )
    
    def test_cross_midnight_playlist_active_before_midnight(self):
        """Test cross-midnight playlist is active before midnight."""
        playlist = Playlist("Night Shift", "22:00", "06:00")
        playlist.plugins.append(self.create_plugin())
        
        # Test at 23:30 - should be active
        self.assertTrue(playlist.is_active("23:30"))
        
    def test_cross_midnight_playlist_active_after_midnight(self):
        """Test cross-midnight playlist is active after midnight."""
        playlist = Playlist("Night Shift", "22:00", "06:00")
        playlist.plugins.append(self.create_plugin())
        
        # Test at 02:00 - should be active
        self.assertTrue(playlist.is_active("02:00"))
        
    def test_cross_midnight_playlist_inactive_during_day(self):
        """Test cross-midnight playlist is inactive during day."""
        playlist = Playlist("Night Shift", "22:00", "06:00")
        playlist.plugins.append(self.create_plugin())
        
        # Test at 14:00 - should NOT be active
        self.assertFalse(playlist.is_active("14:00"))
        
    def test_24_hour_end_time_handling(self):
        """Test playlist with 24:00 as end time."""
        playlist = Playlist("All Day", "00:00", "24:00")
        playlist.plugins.append(self.create_plugin())
        
        # Should be active all day
        self.assertTrue(playlist.is_active("00:00"))
        self.assertTrue(playlist.is_active("12:00"))
        self.assertTrue(playlist.is_active("23:59"))
        
    def test_normal_playlist_boundaries(self):
        """Test normal playlist with start < end."""
        playlist = Playlist("Morning", "08:00", "12:00")
        playlist.plugins.append(self.create_plugin())
        
        # Test boundaries
        self.assertTrue(playlist.is_active("08:00"))  # Start time inclusive
        self.assertTrue(playlist.is_active("11:59"))  # Just before end
        self.assertFalse(playlist.is_active("12:00"))  # End time exclusive
        
    def test_multiple_playlists_priority(self):
        """Test priority when multiple playlists are active."""
        # Create playlists with different time ranges
        playlist1 = Playlist("Wide Range", "08:00", "20:00")  # 12 hours
        playlist1.plugins.append(self.create_plugin())
        
        playlist2 = Playlist("Narrow Range", "10:00", "14:00")  # 4 hours
        playlist2.plugins.append(self.create_plugin())
        
        self.manager.playlists = [playlist1, playlist2]
        
        # At 11:00, both are active, but narrow range should have priority
        current_dt = datetime.strptime("11:00", "%H:%M")
        active = self.manager.determine_active_playlist(current_dt)
        
        self.assertEqual(active.name, "Narrow Range")
        
    def test_no_playlists_configured(self):
        """Test behavior when no playlists exist."""
        current_dt = datetime.now()
        active = self.manager.determine_active_playlist(current_dt)
        
        self.assertIsNone(active)
        
    def test_playlists_without_plugins(self):
        """Test that playlists without plugins are not considered active."""
        playlist = Playlist("Empty", "08:00", "20:00")
        # No plugins added
        
        self.manager.playlists = [playlist]
        current_dt = datetime.strptime("12:00", "%H:%M")
        active = self.manager.determine_active_playlist(current_dt)
        
        self.assertIsNone(active)
        
    def test_invalid_time_format_handling(self):
        """Test error handling for invalid time formats."""
        playlist = Playlist("Invalid", "08:00", "20:00")
        playlist.plugins.append(self.create_plugin())
        
        # Test with invalid time format
        self.assertFalse(playlist.is_active("25:00"))
        self.assertFalse(playlist.is_active("12:60"))
        self.assertFalse(playlist.is_active("invalid"))
        
    def test_cache_functionality(self):
        """Test that caching works correctly."""
        playlist = Playlist("Cached", "08:00", "20:00")
        playlist.plugins.append(self.create_plugin())
        self.manager.playlists = [playlist]
        
        current_dt = datetime.strptime("12:00", "%H:%M")
        
        # First call should calculate
        with patch.object(self.manager, '_calculate_active_playlist') as mock_calc:
            mock_calc.return_value = playlist
            result1 = self.manager.determine_active_playlist(current_dt)
            self.assertEqual(mock_calc.call_count, 1)
        
        # Second call with same time should use cache
        with patch.object(self.manager, '_calculate_active_playlist') as mock_calc:
            result2 = self.manager.determine_active_playlist(current_dt)
            self.assertEqual(mock_calc.call_count, 0)  # Should not be called
            
        self.assertEqual(result1, result2)
        
    def test_cache_invalidation_on_playlist_update(self):
        """Test that cache is invalidated when playlists are modified."""
        playlist = Playlist("Test", "08:00", "20:00")
        playlist.plugins.append(self.create_plugin())
        self.manager.playlists = [playlist]
        
        # Prime the cache
        current_dt = datetime.strptime("12:00", "%H:%M")
        self.manager.determine_active_playlist(current_dt)
        
        # Verify cache exists
        self.assertIsNotNone(self.manager._cache_expiry)
        
        # Update playlist
        self.manager.update_playlist("Test", "Updated", "09:00", "21:00")
        
        # Cache should be invalidated
        self.assertIsNone(self.manager._cache_expiry)
        self.assertEqual(self.manager._active_playlist_cache, {})
        
    def test_find_plugin_to_refresh_no_advance(self):
        """Test that find_plugin_to_refresh doesn't advance index unnecessarily."""
        playlist = Playlist("Test", "00:00", "24:00")
        
        # Add plugins with different refresh settings
        plugin1 = self.create_plugin("plugin1", "Plugin 1")
        plugin2 = self.create_plugin("plugin2", "Plugin 2")
        plugin3 = self.create_plugin("plugin3", "Plugin 3")
        
        playlist.plugins = [plugin1, plugin2, plugin3]
        playlist.current_plugin_index = 0
        
        # Mock should_refresh to return False for all
        for plugin in playlist.plugins:
            plugin.should_refresh = MagicMock(return_value=False)
        
        # Call find_plugin_to_refresh with global_should_refresh=False
        result = playlist.find_plugin_to_refresh(datetime.now(), False)
        
        # Should return None and index should remain at 0
        self.assertIsNone(result)
        self.assertEqual(playlist.current_plugin_index, 0)
        
    def test_find_plugin_to_refresh_with_refresh_needed(self):
        """Test find_plugin_to_refresh when a plugin needs refresh."""
        playlist = Playlist("Test", "00:00", "24:00")
        
        plugin1 = self.create_plugin("plugin1", "Plugin 1")
        plugin2 = self.create_plugin("plugin2", "Plugin 2")
        plugin3 = self.create_plugin("plugin3", "Plugin 3")
        
        playlist.plugins = [plugin1, plugin2, plugin3]
        playlist.current_plugin_index = 0
        
        # Mock should_refresh - only plugin2 needs refresh
        plugin1.should_refresh = MagicMock(return_value=False)
        plugin2.should_refresh = MagicMock(return_value=True)
        plugin3.should_refresh = MagicMock(return_value=False)
        
        result = playlist.find_plugin_to_refresh(datetime.now(), False)
        
        # Should return plugin2 and update index to 1
        self.assertEqual(result, plugin2)
        self.assertEqual(playlist.current_plugin_index, 1)
        
    def test_equal_priority_playlists(self):
        """Test behavior when multiple playlists have the same priority."""
        # Create two playlists with same time range (same priority)
        playlist1 = Playlist("Alpha", "08:00", "12:00")  # 4 hours
        playlist1.plugins.append(self.create_plugin())
        
        playlist2 = Playlist("Beta", "14:00", "18:00")  # 4 hours
        playlist2.plugins.append(self.create_plugin())
        
        self.manager.playlists = [playlist2, playlist1]  # Add in reverse order
        
        # Test when playlist1 is active
        current_dt = datetime.strptime("10:00", "%H:%M")
        active = self.manager.determine_active_playlist(current_dt)
        self.assertEqual(active.name, "Alpha")  # Should be sorted by name
        
        # Test when playlist2 is active
        current_dt = datetime.strptime("16:00", "%H:%M")
        active = self.manager.determine_active_playlist(current_dt)
        self.assertEqual(active.name, "Beta")
        
    def test_error_handling_in_determine_active_playlist(self):
        """Test error handling in determine_active_playlist."""
        # Test with invalid datetime
        result = self.manager.determine_active_playlist("not a datetime")
        self.assertIsNone(result)
        
        # Test with None
        result = self.manager.determine_active_playlist(None)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()