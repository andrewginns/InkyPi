from flask import Blueprint, request, jsonify, current_app, render_template
import logging

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)

@main_bp.route('/')
def main_page():
    device_config = current_app.config['DEVICE_CONFIG']
    return render_template('inky.html', config=device_config.get_config(), plugins=device_config.get_plugins())

@main_bp.route('/playlist_status')
def playlist_status():
    """Check if a playlist is currently active."""
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_info = device_config.get_refresh_info()
    
    return jsonify({
        "playlist_active": refresh_info.refresh_type == "Playlist"
    })

@main_bp.route('/navigate/<direction>', methods=['POST'])
def navigate(direction):
    """Navigate to previous or next image in the playlist."""
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_task = current_app.config['REFRESH_TASK']
    refresh_info = device_config.get_refresh_info()
    
    # Check if a playlist is active
    if refresh_info.refresh_type != "Playlist":
        return jsonify({
            "success": False,
            "error": "No active playlist"
        }), 400
    
    playlist_manager = device_config.get_playlist_manager()
    playlist = playlist_manager.get_playlist(refresh_info.playlist)
    
    if not playlist or not playlist.plugins:
        return jsonify({
            "success": False,
            "error": "Invalid playlist or no plugins"
        }), 400
    
    try:
        # Navigate to the next/previous plugin
        if direction == "next":
            plugin_instance = playlist.get_next_plugin()
        elif direction == "previous":
            plugin_instance = playlist.get_previous_plugin()
        else:
            return jsonify({
                "success": False,
                "error": "Invalid navigation direction"
            }), 400
        
        # Trigger a manual refresh
        from refresh_task import PlaylistRefresh
        refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )
        
        logger.info(f"Navigated {direction} to plugin '{plugin_instance.name}'")
        
        return jsonify({
            "success": True,
            "plugin": plugin_instance.name
        })
        
    except Exception as e:
        logger.exception(f"Error navigating {direction}: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
