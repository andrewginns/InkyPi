from flask import Blueprint, request, jsonify, current_app, render_template, url_for
import logging
import os

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)

@main_bp.route('/')
def main_page():
    device_config = current_app.config['DEVICE_CONFIG']
    return render_template('inky.html', config=device_config.get_config(), plugins=device_config.get_plugins())

@main_bp.route('/playlist_status')
def playlist_status():
    """Check if a playlist is currently active and return playlist details."""
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_info = device_config.get_refresh_info()
    
    response = {
        "playlist_active": refresh_info.refresh_type == "Playlist"
    }
    
    # If playlist is active, include current index
    if response["playlist_active"]:
        playlist_manager = device_config.get_playlist_manager()
        playlist = playlist_manager.get_playlist(refresh_info.playlist)
        if playlist and playlist.current_plugin_index is not None:
            response["current_index"] = playlist.current_plugin_index
    
    return jsonify(response)

@main_bp.route('/playlist/images')
def playlist_images():
    """Get all image URLs in the current playlist."""
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_info = device_config.get_refresh_info()
    
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
    
    # For image_upload plugin, we need to handle multiple images within one plugin instance
    images = []
    
    # Find the current plugin instance
    current_plugin = None
    for plugin_instance in playlist.plugins:
        if plugin_instance.plugin_id == refresh_info.plugin_id and plugin_instance.name == refresh_info.plugin_instance:
            current_plugin = plugin_instance
            break
    
    if not current_plugin:
        return jsonify({
            "success": False,
            "error": "Current plugin not found"
        }), 400
    
    # Check if this is an image_upload plugin with multiple images
    if current_plugin.plugin_id == "image_upload" and "imageFiles[]" in current_plugin.settings:
        image_files = current_plugin.settings.get("imageFiles[]", [])
        current_index = current_plugin.settings.get("image_index", 0)
        
        for i, image_path in enumerate(image_files):
            # Extract just the filename from the full path
            filename = os.path.basename(image_path)
            
            # Check if the image exists
            full_path = os.path.join(current_app.root_path, "static", "images", "saved", filename)
            
            if os.path.exists(full_path):
                images.append({
                    "index": i,
                    "url": url_for('static', filename=f'images/saved/{filename}'),
                    "name": filename
                })
            else:
                # Use current image as fallback
                images.append({
                    "index": i,
                    "url": url_for('static', filename='images/current_image.png'),
                    "name": filename
                })
        
        return jsonify({
            "success": True,
            "images": images,
            "current_index": current_index
        })
    else:
        # For non-image_upload plugins, return just the current image
        return jsonify({
            "success": True,
            "images": [{
                "index": 0,
                "url": url_for('static', filename='images/current_image.png'),
                "name": current_plugin.name
            }],
            "current_index": 0
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

@main_bp.route('/navigate/to/<int:index>', methods=['POST'])
def navigate_to_index(index):
    """Navigate to a specific image index."""
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
    
    # Find the current plugin instance
    current_plugin = None
    for plugin_instance in playlist.plugins:
        if plugin_instance.plugin_id == refresh_info.plugin_id and plugin_instance.name == refresh_info.plugin_instance:
            current_plugin = plugin_instance
            break
    
    if not current_plugin:
        return jsonify({
            "success": False,
            "error": "Current plugin not found"
        }), 400
    
    try:
        # For image_upload plugin, update the image_index
        if current_plugin.plugin_id == "image_upload" and "imageFiles[]" in current_plugin.settings:
            image_files = current_plugin.settings.get("imageFiles[]", [])
            
            # Validate index
            if index < 0 or index >= len(image_files):
                return jsonify({
                    "success": False,
                    "error": f"Invalid index: {index}"
                }), 400
            
            # Update the image index
            current_plugin.settings["image_index"] = index
            
            # Save the updated configuration BEFORE triggering refresh
            device_config.write_config()
            
            # Trigger a manual refresh
            from refresh_task import PlaylistRefresh
            refresh_task.manual_update(
                PlaylistRefresh(playlist, current_plugin, force=True)
            )
            
            logger.info(f"Navigated to image index {index}")
            
            return jsonify({
                "success": True,
                "index": index
            })
        else:
            # For non-image_upload plugins, just refresh
            from refresh_task import PlaylistRefresh
            refresh_task.manual_update(
                PlaylistRefresh(playlist, current_plugin, force=True)
            )
            
            return jsonify({
                "success": True,
                "index": 0
            })
        
    except Exception as e:
        logger.exception(f"Error navigating to index {index}: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
