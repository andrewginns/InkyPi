import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class RefreshInfo:
    """Keeps track of refresh metadata.

    Attributes:
        refresh_time (str): ISO-formatted time string of the refresh.
        image_hash (int): SHA-256 hash of the image.
        refresh_type (str): Refresh type ['Manual Update', 'Playlist'].
        plugin_id (str): Plugin id of the refresh.
        playlist (str): Playlist name if refresh_type is 'Playlist'.
        plugin_instance (str): Plugin instance name if refresh_type is 'Playlist'.
    """

    def __init__(self, refresh_type, plugin_id, refresh_time, image_hash, playlist=None, plugin_instance=None):
        """Initialize RefreshInfo instance."""
        self.refresh_time = refresh_time
        self.image_hash = image_hash
        self.refresh_type = refresh_type
        self.plugin_id = plugin_id
        self.playlist = playlist
        self.plugin_instance = plugin_instance

    def get_refresh_datetime(self):
        """Returns the refresh time as a datetime object or None if not set."""
        latest_refresh = None
        if self.refresh_time:
            latest_refresh = datetime.fromisoformat(self.refresh_time)
        return latest_refresh

    def to_dict(self):
        refresh_dict = {
            "refresh_time": self.refresh_time,
            "image_hash": self.image_hash,
            "refresh_type": self.refresh_type,
            "plugin_id": self.plugin_id,
        }
        if self.playlist:
            refresh_dict["playlist"] = self.playlist
        if self.plugin_instance:
            refresh_dict["plugin_instance"] = self.plugin_instance
        return refresh_dict

    @classmethod
    def from_dict(cls, data):
        return cls(
            refresh_time=data.get("refresh_time"),
            image_hash=data.get("image_hash"),
            refresh_type=data.get("refresh_type"),
            plugin_id=data.get("plugin_id"),
            playlist=data.get("playlist"),
            plugin_instance=data.get("plugin_instance")
        )

class PlaylistManager:
    """A class managing multiple time-based playlists.

    Attributes:
        playlists (list): A list of Playlist instances managed by the manager.
        active_playlist (str): Name of the currently active playlist.
    """
    DEFAULT_PLAYLIST_START = "00:00"
    DEFAULT_PLAYLIST_END = "24:00"

    def __init__(self, playlists=[], active_playlist=None):
        """Initialize PlaylistManager with a list of playlists."""
        self.playlists = playlists
        # active_playlist field removed - now calculated in real-time
        self._active_playlist_cache = {}
        self._cache_expiry = None

    def get_playlist_names(self):
        """Returns a list of all playlist names."""
        return [p.name for p in self.playlists]

    def add_default_playlist(self):
        """Add a default playlist to the manager, called when no playlists exist."""
        return self.playlists.append(
            Playlist("Default", PlaylistManager.DEFAULT_PLAYLIST_START, PlaylistManager.DEFAULT_PLAYLIST_END, []))

    def find_plugin(self, plugin_id, instance):
        """Searches playlists to find a plugin with the given ID and instance."""
        for playlist in self.playlists:
            plugin = playlist.find_plugin(plugin_id, instance)
            if plugin:
                return plugin
        return None

    def determine_active_playlist(self, current_datetime):
        """Determine the active playlist based on the current time with caching and comprehensive error handling."""
        from datetime import timedelta
        
        # Validate input
        if not hasattr(current_datetime, 'strftime'):
            logger.error(f"Invalid datetime provided to determine_active_playlist: expected datetime object, got {type(current_datetime)}")
            return None
        
        # Check cache first
        try:
            cache_key = current_datetime.strftime("%H:%M")
        except Exception as e:
            logger.error(f"Error formatting datetime: {e}")
            return None
            
        if (self._cache_expiry and 
            current_datetime < self._cache_expiry and 
            cache_key in self._active_playlist_cache):
            cached_playlist = self._active_playlist_cache[cache_key]
            logger.debug(f"Using cached active playlist: '{cached_playlist.name if cached_playlist else None}'")
            return cached_playlist
        
        # Calculate active playlist
        active_playlist = self._calculate_active_playlist(current_datetime)
        
        # Update cache - cache for 1 minute to avoid repeated calculations
        self._active_playlist_cache = {cache_key: active_playlist}
        self._cache_expiry = current_datetime + timedelta(minutes=1)
        
        return active_playlist
    
    def _calculate_active_playlist(self, current_datetime):
        """Internal method to calculate active playlist without caching."""
        if not self.playlists:
            logger.info("No playlists configured in playlist manager")
            return None
        
        try:
            current_time = current_datetime.strftime("%H:%M")  # Get current time in "HH:MM" format
        except (AttributeError, ValueError) as e:
            logger.error(f"Invalid datetime provided to determine_active_playlist: {e}")
            return None

        # Filter active playlists with plugins, handling errors gracefully
        active_playlists = []
        for playlist in self.playlists:
            try:
                if playlist.is_active(current_time) and playlist.plugins:
                    active_playlists.append(playlist)
            except Exception as e:
                logger.error(f"Error checking if playlist '{getattr(playlist, 'name', 'unknown')}' is active: {e}")
                continue
        
        if not active_playlists:
            logger.debug(f"No active playlists with plugins found at {current_time}")
            return None

        # Sort by priority with tie-breaking by name for consistency
        try:
            active_playlists.sort(key=lambda p: (p.get_priority(), p.name))
        except Exception as e:
            logger.error(f"Error sorting playlists by priority: {e}")
            # Return first playlist as fallback if sorting fails
            return active_playlists[0] if active_playlists else None

        playlist = active_playlists[0]
        logger.debug(f"Active playlist determined: '{playlist.name}' at {current_time}")
        
        return playlist

    def get_active_playlist_name(self, current_datetime=None):
        """Get the name of the currently active playlist in real-time."""
        if current_datetime is None:
            from datetime import datetime
            current_datetime = datetime.now()
        
        active = self.determine_active_playlist(current_datetime)
        return active.name if active else None
    
    def invalidate_cache(self):
        """Invalidate the active playlist cache. Should be called when playlists are modified."""
        self._active_playlist_cache = {}
        self._cache_expiry = None
        logger.debug("Active playlist cache invalidated")

    def get_playlist(self, playlist_name):
        """Returns the playlist with the specified name."""
        return next((p for p in self.playlists if p.name == playlist_name), None)

    def add_plugin_to_playlist(self, playlist_name, plugin_data):
        """Adds a plugin to a playlist by the specified name. Returns true if successfully added,
        False if playlist doesn't exist"""
        playlist = self.get_playlist(playlist_name)
        if playlist:
            if playlist.add_plugin(plugin_data):
                self.invalidate_cache()  # Invalidate cache when playlist is modified
                return True
        else:
            logger.warning(f"Playlist '{playlist_name}' not found.")
        return False

    def add_playlist(self, name, start_time=None, end_time=None):
        """Creates and adds a new playlist with the given start and end times."""
        if not start_time:
            start_time = PlaylistManager.DEFAULT_PLAYLIST_START
        if not end_time:
            end_time = PlaylistManager.DEFAULT_PLAYLIST_END
        self.playlists.append(Playlist(name, start_time, end_time))
        self.invalidate_cache()  # Invalidate cache when playlist is added
        return True

    def update_playlist(self, old_name, new_name, start_time, end_time):
        """Updates an existing playlist's name, start time, and end time."""
        playlist = self.get_playlist(old_name)
        if playlist:
            playlist.name = new_name
            playlist.start_time = start_time
            playlist.end_time = end_time
            self.invalidate_cache()  # Invalidate cache when playlist is updated
            return True
        logger.warning(f"Playlist '{old_name}' not found.")
        return False

    def delete_playlist(self, name):
        """Deletes the playlist with the specified name."""
        self.playlists = [p for p in self.playlists if p.name != name]
        self.invalidate_cache()  # Invalidate cache when playlist is deleted

    def to_dict(self):
        return {
            "playlists": [p.to_dict() for p in self.playlists]
            # active_playlist field removed - now calculated in real-time
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            playlists=[Playlist.from_dict(p) for p in data.get("playlists", [])]
            # active_playlist parameter removed - now calculated in real-time
        )

    @staticmethod
    def should_refresh(latest_refresh, interval_seconds, current_time):
        """Determines whether a refresh should occur on the interval and latest refresh time."""
        if not latest_refresh:
            return True  # No previous refresh, so it's time to refresh

        return (current_time - latest_refresh) >= timedelta(seconds=interval_seconds)

class Playlist:
    """Represents a playlist with a time interval.

    Attributes:
        name (str): Name of the playlist.
        start_time (str): Playlist start time in 'HH:MM'.
        end_time (str): Playlist end time in 'HH:MM'.
        plugins (list): A list of PluginInstance objects within the playlist.
        current_plugin_index (int): Index of the currently active plugin in the playlist.
    """

    def __init__(self, name, start_time, end_time, plugins=None, current_plugin_index=None):
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.plugins = [PluginInstance.from_dict(p) for p in (plugins or [])]
        self.current_plugin_index = current_plugin_index

    def is_active(self, current_time):
        """Check if the playlist is active at the given time.
        
        Handles cross-midnight playlists (e.g., 22:00 to 06:00) and special
        cases like "24:00" as end time.
        """
        from datetime import datetime, time as dt_time
        
        try:
            # Parse current time
            current_dt = datetime.strptime(current_time, "%H:%M").time()
            start_dt = datetime.strptime(self.start_time, "%H:%M").time()
            
            # Handle special case of "24:00" as end time (midnight)
            if self.end_time == "24:00":
                end_dt = dt_time(23, 59, 59, 999999)  # Just before midnight
            else:
                end_dt = datetime.strptime(self.end_time, "%H:%M").time()
            
            # Handle cross-midnight playlists (e.g., 22:00 to 06:00)
            if start_dt > end_dt:
                # Playlist spans midnight
                return current_dt >= start_dt or current_dt < end_dt
            else:
                # Normal case: playlist within same day
                return start_dt <= current_dt < end_dt
                
        except ValueError as e:
            logger.error(f"Invalid time format in playlist '{self.name}': {e}")
            return False

    def add_plugin(self, plugin_data):
        """Add a new plugin instance to the playlist."""
        if self.find_plugin(plugin_data["plugin_id"], plugin_data["name"]):
            logger.warning(f"Plugin '{plugin_data['plugin_id']}' with instance '{plugin_data['name']}' already exists.")
            return False
        self.plugins.append(PluginInstance.from_dict(plugin_data))
        return True

    def update_plugin(self, plugin_id, instance_name, updated_data):
        """Updates an existing plugin instance in the playlist."""
        plugin = self.find_plugin(plugin_id, instance_name)
        if plugin:
            plugin.update(updated_data)
            return True
        logger.warning(f"Plugin '{plugin_id}' with name '{instance_name}' not found.")
        return False

    def delete_plugin(self, plugin_id, name):
        """Remove a specific plugin instance from the playlist."""
        initial_count = len(self.plugins)
        self.plugins = [p for p in self.plugins if not (p.plugin_id == plugin_id and p.name == name)]
        
        if len(self.plugins) == initial_count:
            logger.warning(f"Plugin '{plugin_id}' with instance '{name}' not found.")
            return False
        return True

    def find_plugin(self, plugin_id, name):
        """Find a plugin instance by its plugin_id and name."""
        return next((p for p in self.plugins if p.plugin_id == plugin_id and p.name == name), None)

    def get_next_plugin(self):
        """Returns the next plugin instance in the playlist and update the current_plugin_index."""
        if self.current_plugin_index is None:
            self.current_plugin_index = 0
        else:
            self.current_plugin_index = (self.current_plugin_index + 1) % len(self.plugins)
        
        return self.plugins[self.current_plugin_index]

    def find_plugin_to_refresh(self, current_dt, global_should_refresh):
        """Find the next plugin that needs refreshing without advancing indices unnecessarily.
        
        This method checks all plugins to find one that needs refresh without
        modifying the current_plugin_index unless a plugin is found that needs refresh.
        
        Args:
            current_dt: Current datetime for checking refresh schedules
            global_should_refresh: Whether global refresh interval has elapsed
            
        Returns:
            Plugin instance that needs refresh, or None if no plugins need refresh
        """
        if not self.plugins:
            return None
        
        # First, check if current plugin needs refresh
        if self.current_plugin_index is not None and 0 <= self.current_plugin_index < len(self.plugins):
            current_plugin = self.plugins[self.current_plugin_index]
            if current_plugin.should_refresh(current_dt) or global_should_refresh:
                logger.debug(f"Current plugin '{current_plugin.name}' needs refresh")
                return current_plugin
        
        # Check all plugins starting from next index
        start_index = (self.current_plugin_index + 1) if self.current_plugin_index is not None else 0
        for i in range(len(self.plugins)):
            index = (start_index + i) % len(self.plugins)
            plugin = self.plugins[index]
            
            if plugin.should_refresh(current_dt) or global_should_refresh:
                logger.debug(f"Plugin '{plugin.name}' at index {index} needs refresh")
                self.current_plugin_index = index
                return plugin
        
        logger.debug("No plugins need refresh in playlist")
        return None

    def get_priority(self):
        """Determine priority of a playlist, based on the time range"""
        return self.get_time_range_minutes()

    def get_time_range_minutes(self):
        """Calculate the time difference in minutes between start_time and end_time."""
        start = datetime.strptime(self.start_time, "%H:%M")
        # Handle '24:00' by converting it to '00:00' of the next day
        if self.end_time != "24:00":
            end = datetime.strptime(self.end_time, "%H:%M")
        else:
            end = datetime.strptime("00:00", "%H:%M")
            end += timedelta(days=1)

        return int((end - start).total_seconds() // 60)

    def to_dict(self):
        return {
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "plugins": [p.to_dict() for p in self.plugins],
            "current_plugin_index": self.current_plugin_index
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data["name"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            plugins=data["plugins"],
            current_plugin_index=data.get("current_plugin_index", None)
        )

class PluginInstance:
    """Represents an individual plugin instance within a playlist.

    Attributes:
        plugin_id (str): Plugin id for this instance.
        name (str): Name of the plugin instance.
        settings (dict): Settings associated with the plugin.
        refresh (dict): Refresh settings, such as interval and scheduled time.
        latest_refresh (str): ISO-formatted string representing the last refresh time.
    """

    def __init__(self, plugin_id, name, settings, refresh, latest_refresh_time=None):
        self.plugin_id = plugin_id
        self.name = name
        self.settings = settings
        self.refresh = refresh
        self.latest_refresh_time = latest_refresh_time

    def update(self, updated_data):
        """Update attributes of the class with the dictionary values."""
        for key, value in updated_data.items():
            setattr(self, key, value)

    def should_refresh(self, current_time):
        """Checks whether the plugin should be refreshed based on its refresh settings and the current time."""
        latest_refresh_dt = self.get_latest_refresh_dt()
        if not latest_refresh_dt:
            return True

        # Check for interval-based refresh
        if "interval" in self.refresh:
            interval = self.refresh.get("interval")
            if interval and (current_time - latest_refresh_dt) >= timedelta(seconds=interval):
                return True

        # Check for scheduled refresh (HH:MM format)
        if "scheduled" in self.refresh:
            scheduled_time_str = self.refresh.get("scheduled")
            latest_refresh_str = latest_refresh_dt.strftime("%H:%M")

            # If the latest refresh is before the scheduled time today
            if latest_refresh_str < scheduled_time_str:
                return True
        
        if "scheduled" in self.refresh:
            scheduled_time_str = self.refresh.get("scheduled")
            scheduled_time = datetime.strptime(scheduled_time_str, "%H:%M").time()
            
            latest_refresh_date = latest_refresh_dt.date()
            current_date = current_time.date()

            # Determine if a refresh is needed based on scheduled time and last refresh
            if (latest_refresh_date < current_date and current_time.time() >= scheduled_time) or \
            (latest_refresh_date == current_date and latest_refresh_dt.time() < scheduled_time <= current_time.time()):
                return True

        return False

    def get_image_path(self):
        """Formats the image path for this plugin instance."""
        return f"{self.plugin_id}_{self.name.replace(' ', '_')}.png"

    def get_latest_refresh_dt(self):
        """Returns the latest refresh time as a datetime object, or None if not set."""
        latest_refresh = None
        if self.latest_refresh_time:
            latest_refresh = datetime.fromisoformat(self.latest_refresh_time)
        return latest_refresh
    
    def to_dict(self):
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "plugin_settings": self.settings,
            "refresh": self.refresh,
            "latest_refresh_time": self.latest_refresh_time,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            plugin_id=data["plugin_id"],
            name=data["name"],
            settings=data["plugin_settings"],
            refresh=data["refresh"],
            latest_refresh_time=data.get("latest_refresh_time"),
        )