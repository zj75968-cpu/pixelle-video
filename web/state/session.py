# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Session state management for web UI
"""

import streamlit as st
from loguru import logger

from web.i18n import get_language, set_language
from web.utils.async_helpers import run_async


def init_session_state():
    """Initialize session state variables"""
    if "language" not in st.session_state:
        # Use auto-detected system language
        st.session_state.language = get_language()


def init_i18n():
    """Initialize internationalization"""
    # Locales are already loaded and system language detected on import
    # Get language from session state or use auto-detected system language
    if "language" not in st.session_state:
        st.session_state.language = get_language()  # Use auto-detected language
    
    # Set current language
    set_language(st.session_state.language)


def get_pixelle_video():
    """
    Get initialized Pixelle-Video instance with proper caching and cleanup
    
    Uses st.session_state to cache the instance per user session.
    ComfyKit is lazily initialized and automatically recreated on config changes.
    """
    from pixelle_video.service import PixelleVideoCore
    from pixelle_video.config import config_manager
    
    # Compute config hash for change detection
    import hashlib
    import json
    import hashlib
    import inspect
    import json
    config_dict = config_manager.config.to_dict()
    # Only track ComfyUI config for hash (other config changes don't need core recreation)
    comfyui_config = config_dict.get("comfyui", {})
    config_hash = hashlib.md5(json.dumps(comfyui_config, sort_keys=True).encode()).hexdigest()

    # Also hash pipeline source so code changes (hot-reload) invalidate the cache
    pipeline_src_hash = None
    try:
        from pixelle_video.pipelines.image_text_post import ImageTextPostPipeline
        src = inspect.getsource(ImageTextPostPipeline)
        pipeline_src_hash = hashlib.md5(src.encode()).hexdigest()
        logger.debug(f"[session] pipeline_src_hash computed: {pipeline_src_hash[:8]}...")
    except ImportError as e:
        logger.warning(f"[session] Failed to import ImageTextPostPipeline: {e}")
        pipeline_src_hash = "import_error"  # Force cache invalidation
    except Exception as e:
        logger.warning(f"[session] Failed to compute pipeline hash: {e}")
        pipeline_src_hash = "hash_error"  # Force cache invalidation
    
    combined_hash = f"{config_hash}:{pipeline_src_hash}"
    logger.info(f"[session] combined_hash = {combined_hash[:16]}...")
    
    # Check if we need to create or recreate core instance
    need_recreate = False
    prev_hash = st.session_state.get('pixelle_video_config_hash')
    if 'pixelle_video' not in st.session_state:
        need_recreate = True
        logger.info("[session] Creating new PixelleVideoCore instance (first time)")
    elif prev_hash != combined_hash:
        need_recreate = True
        logger.info(f"[session] Hash mismatch: prev={prev_hash[:16]}... vs new={combined_hash[:16]}...")
        logger.info("[session] Configuration or pipeline code changed, recreating PixelleVideoCore instance")
        # Cleanup old instance
        old_core = st.session_state.pixelle_video
        try:
            run_async(old_core.cleanup())
        except Exception as e:
            logger.warning(f"[session] Failed to cleanup old PixelleVideoCore: {e}")
    
    if need_recreate:
        # Create and initialize new instance
        pixelle_video = PixelleVideoCore()
        run_async(pixelle_video.initialize())
        
        # Cache in session state
        st.session_state.pixelle_video = pixelle_video
        st.session_state.pixelle_video_config_hash = combined_hash
        logger.info(f"[session] ✅ PixelleVideoCore initialized and cached with hash {combined_hash[:16]}...")
    else:
        pixelle_video = st.session_state.pixelle_video
        logger.debug(f"[session] Reusing cached PixelleVideoCore instance (hash: {combined_hash[:16]}...)")
    
    return pixelle_video

