import os
import re
import sys
import time
import json
import logging
import requests
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from configparser import ConfigParser
from threading import Lock
_progress_lock = Lock()
_progress_total = 1
_progress_done = 0

def _progress_set_total(n: int):
    global _progress_total, _progress_done
    with _progress_lock:
        _progress_total = max(1, int(n))
        _progress_done = 0
        print("PROGRESS 0"); sys.stdout.flush()

def _progress_step(k: int = 1):
    global _progress_done, _progress_total
    with _progress_lock:
        _progress_done += k
        pct = int((_progress_done * 100) / _progress_total)
    print(f"PROGRESS {min(100, max(0, pct))}")
    sys.stdout.flush()

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Thread-local storage for requests session
thread_local = threading.local()

def get_session():
    """Get thread-local session for connection pooling"""
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session

HTTP_TIMEOUT = 30
HTTP_RETRIES = 3 

def make_request(url, headers, timeout=HTTP_TIMEOUT):
    session = get_session()
    for attempt in range(HTTP_RETRIES):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ReadTimeout:
            if attempt < HTTP_RETRIES - 1:
                continue  # try again
            else:
                raise
        except requests.exceptions.ConnectionError:
            if attempt < HTTP_RETRIES - 1:
                continue
            else:
                raise

def find_movies_by_title(server, token, title):
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    libs = make_request(f'{server}/library/sections', headers)['MediaContainer']['Directory']

    results = []
    for lib in libs:
        if lib.get('type') != 'movie':
            continue
        key = lib.get('key')
        lib_title = lib.get('title')
        resp = make_request(f"{server}/library/sections/{key}/all?title={requests.utils.quote(title)}", headers)
        for m in resp.get('MediaContainer', {}).get('Metadata', []) or []:
            # Return just what we need to show and to process
            results.append({
                'ratingKey': m.get('ratingKey'),
                'title':     m.get('title'),
                'year':      m.get('year'),
                'thumb':     m.get('thumb'),
                'library':   lib_title,
                'raw':       m,  # minimal object in case we want to process directly
            })
    return results

def get_movie_by_rating_key(server, token, rating_key):
    """Fetch full movie metadata given a ratingKey."""
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    data = make_request(f'{server}/library/metadata/{rating_key}', headers)
    md = (data.get('MediaContainer', {}).get('Metadata') or [])
    return md[0] if md else None


# Initialize settings
def initialize_settings():
    config_file = Path(__file__).parent / 'config' / 'config.ini'
    config = ConfigParser()
    config.read(config_file)

    server = config.get('server', 'address')
    token = config.get('server', 'token')

    skip_libraries = set(re.split(r'[；;]', config.get('server', 'skip_libraries', fallback=""))) if config.has_option('server', 'skip_libraries') else set()
    modules = re.split(r'[；;]', config.get('modules', 'order', fallback="")) if config.has_option('modules', 'order') else [
        "AudioChannels", "AudioCodec", "Bitrate", "ContentRating", "Country", "Cut",
        "Director", "Duration", "DynamicRange", "FrameRate", "Genre",
        "Language", "Rating", "Release", "Resolution", "Size",
        "Source", "SpecialFeatures", "Studio", "VideoCodec"
    ]

    excluded_languages = set()
    if config.has_option('language', 'excluded_languages'):
        excluded_languages = {
            lang.strip() for lang in re.split(r'[,;]', config.get('language', 'excluded_languages'))
            if lang.strip()
        }

    skip_multiple_audio_tracks = config.getboolean(
        'language',
        'skip_multiple_audio_tracks',
        fallback=False
    )

    tmdb_api_key = config.get('rating', 'tmdb_api_key', fallback=None)

    max_workers = config.getint('performance', 'max_workers', fallback=10)
    batch_size = config.getint('performance', 'batch_size', fallback=25)

    try:
        headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
        response = make_request(f'{server}/library/sections', headers)
        server_name = response['MediaContainer'].get('friendlyName', server)
        logger.info(f"Successfully connected to server: {server_name}")
    except requests.exceptions.RequestException as err:
        logger.error("Server connection failed, please check the settings in the configuration file or your network.")
        time.sleep(10)
        raise SystemExit(err)

    return (
        server,
        token,
        skip_libraries,
        modules,
        excluded_languages,
        skip_multiple_audio_tracks,
        tmdb_api_key,
        max_workers,
        batch_size
    )

# Batched movie processing
def process_movies_batch(
    movies_batch,
    server,
    token,
    modules,
    excluded_languages,
    skip_multiple_audio_tracks,
    tmdb_api_key,
    lib_title=""
):
    for movie in movies_batch:
        try:
            process_single_movie(
                server,
                token,
                movie,
                modules,
                excluded_languages,
                skip_multiple_audio_tracks,
                tmdb_api_key
            )
        except Exception as e:
            logger.error(f"Error processing movie {movie.get('title', 'Unknown')}: {str(e)}")

# Main movie processing function
def process_movies(
    server,
    token,
    skip_libraries,
    modules,
    excluded_languages,
    skip_multiple_audio_tracks,
    tmdb_api_key,
    max_workers,
    batch_size
):
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    libraries = make_request(f'{server}/library/sections', headers)['MediaContainer']['Directory']

    all_movies = []
    library_info = {}
    for library in libraries:
        if library.get('type') == 'movie' and library.get('title') not in skip_libraries:
            lib_title = library.get('title')
            resp = make_request(f"{server}/library/sections/{library['key']}/all", headers)
            movies = resp.get('MediaContainer', {}).get('Metadata', []) if resp else []
            all_movies.extend(movies)
            library_info[lib_title] = len(movies)

    logger.info(f"Total movies found: {len(all_movies)}")
    for lib_title, count in library_info.items():
        logger.info(f"Library: {lib_title}, Movies: {count}")

    _progress_set_total(len(all_movies))

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for i in range(0, len(all_movies), batch_size):
            batch = all_movies[i:i+batch_size]
            futures = [
                executor.submit(
                    process_single_movie,
                    server,
                    token,
                    m,
                    modules,
                    excluded_languages,
                    skip_multiple_audio_tracks,
                    tmdb_api_key
                )
                for m in batch
            ]
            for _ in as_completed(futures):
                _progress_step()
            logger.info(
                f"Processed batch {i//batch_size + 1}/{(len(all_movies)+batch_size-1)//batch_size}"
            )

# Process a single movie
def process_single_movie(
    server,
    token,
    movie,
    modules,
    excluded_languages,
    skip_multiple_audio_tracks,
    tmdb_api_key
):
    # 1. get full metadata
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    movie_id = movie['ratingKey']

    detailed_movie = None
    try:
        detailed_response = get_session().get(
            f'{server}/library/metadata/{movie_id}',
            headers=headers
        )
        if detailed_response.status_code == 200:
            detailed_data = detailed_response.json()
            if 'MediaContainer' in detailed_data and 'Metadata' in detailed_data['MediaContainer']:
                detailed_movie = detailed_data['MediaContainer']['Metadata'][0]
    except Exception as e:
        logger.warning(f"Could not fetch detailed metadata for movie {movie.get('title', 'Unknown')}: {str(e)}")

    movie_data = detailed_movie if detailed_movie else movie

    # 2. figure out filename (needed for Cut / Release / Source)
    media_list = movie_data.get('Media', [])
    if not media_list:
        return

    first_media = media_list[0]
    media_parts = first_media.get('Part', [])
    if not media_parts:
        return

    max_size_part = max(media_parts, key=lambda part: part['size'])
    file_path = max_size_part['file']
    file_name = os.path.basename(file_path)

    tags = []

    # 3. import modules
    from modules.AudioChannels import get_AudioChannels
    from modules.AudioCodec import get_AudioCodec
    from modules.Bitrate import get_Bitrate
    from modules.ContentRating import get_ContentRating
    from modules.Country import get_Country
    from modules.Cut import get_Cut
    from modules.Director import get_Director
    from modules.Duration import get_Duration
    from modules.DynamicRange import get_DynamicRange
    from modules.FrameRate import get_FrameRate
    from modules.Genre import get_Genre
    from modules.Language import get_Language
    from modules.Rating import get_Rating
    from modules.Release import get_Release
    from modules.Resolution import get_Resolution
    from modules.ShortFilm import get_ShortFilm
    from modules.Size import get_Size
    from modules.Source import get_Source
    from modules.SpecialFeatures import get_SpecialFeatures
    from modules.Studio import get_Studio
    from modules.VideoCodec import get_VideoCodec
    from modules.Writer import get_Writer

    # 4. run modules
    for module in modules:
        try:
            if module == 'AudioChannels':
                v = get_AudioChannels(movie_data)
            elif module == 'AudioCodec':
                v = get_AudioCodec(movie_data)
            elif module == 'Bitrate':
                v = get_Bitrate(movie_data)
            elif module == 'ContentRating':
                v = get_ContentRating(movie_data)
            elif module == 'Country':
                v = get_Country(movie_data)
            elif module == 'Cut':
                v = get_Cut(file_name)
            elif module == 'Director':
                v = get_Director(movie_data)
            elif module == 'Duration':
                v = get_Duration(movie_data)
            elif module == 'DynamicRange':
                v = get_DynamicRange(movie_data)
            elif module == 'FrameRate':
                v = get_FrameRate(movie_data)
            elif module == 'Genre':
                v = get_Genre(movie_data)
            elif module == 'Language':
                v = get_Language(
                    movie_data,
                    excluded_languages,
                    skip_multiple_audio_tracks
                )
            elif module == 'Rating':
                v = get_Rating(movie_data, tmdb_api_key)
            elif module == 'Release':
                v = get_Release(file_name)
            elif module == 'Resolution':
                v = get_Resolution(movie_data)
            elif module == 'ShortFilm':
                v = get_ShortFilm(movie_data)
            elif module == 'Size':
                v = get_Size(movie_data)
            elif module == 'Source':
                v = get_Source(file_name, movie_data)
            elif module == 'SpecialFeatures':
                v = get_SpecialFeatures(movie_data)
            elif module == 'Studio':
                v = get_Studio(movie_data)
            elif module == 'VideoCodec':
                v = get_VideoCodec(movie_data)
            elif module == 'Writer':
                v = get_Writer(movie_data)
            else:
                v = None

            if v:
                tags.append(v)

        except Exception as e:
            logger.error(
                f"Error processing module {module} for {movie_data.get('title', 'Unknown')}: {str(e)}"
            )

    update_movie(server, token, movie_data, tags, modules)

def process_movie_by_rating_key(
    server, token, rating_key, modules, excluded_languages, skip_multiple_audio_tracks, tmdb_api_key
):
    movie = get_movie_by_rating_key(server, token, rating_key)
    if not movie:
        logger.error(f"Movie with ratingKey {rating_key} not found.")
        return False

    # Log and send initial progress signal for GUI
    logger.info(f"Processing ratingKey={rating_key} ...")
    print("PROGRESS 0")
    sys.stdout.flush()

    # Run the standard single-movie processing routine
    process_single_movie(
        server, token, movie, modules, excluded_languages, skip_multiple_audio_tracks, tmdb_api_key
    )

    # Send completion signal for GUI progress bar
    print("PROGRESS 100")
    sys.stdout.flush()

    return True

def update_movie(server, token, movie, tags, modules):
    movie_id = movie['ratingKey']
    title = movie.get('title', 'Unknown')
   
    clear_params = {
        'type': 1,
        'id': movie_id,
        'editionTitle.value': '',
        'editionTitle.locked': 0
    }
    session = get_session()
    session.put(
        f'{server}/library/metadata/{movie_id}',
        headers={'X-Plex-Token': token},
        params=clear_params
    )

    tags = list(dict.fromkeys(tags))

    if tags:
        edition_title = ' · '.join(tags)
        params = {
            'type': 1,
            'id': movie_id,
            'editionTitle.value': edition_title,
            'editionTitle.locked': 1
        }

        session.put(
            f'{server}/library/metadata/{movie_id}',
            headers={'X-Plex-Token': token},
            params=params
        )
        logger.info(f'{title}: {edition_title}')
    else:
        logger.info(f'{title}: Cleared edition information')
    
    return True

# Reset movies with multi-threading
def reset_movies(server, token, skip_libraries, max_workers, batch_size):
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    libraries = make_request(f'{server}/library/sections', headers)['MediaContainer']['Directory']

    to_reset = []
    for lib in libraries:
        if lib.get('type') == 'movie' and lib.get('title') not in skip_libraries:
            resp = make_request(f"{server}/library/sections/{lib['key']}/all", headers)
            movies = resp.get('MediaContainer', {}).get('Metadata', []) if resp else []
            to_reset.extend([m for m in movies if 'editionTitle' in m])

    logger.info(f"Total movies to reset: {len(to_reset)}")
    _progress_set_total(len(to_reset))

    from concurrent.futures import ThreadPoolExecutor, as_completed
    def _reset_one(movie):
        movie_id = movie['ratingKey']
        params = {'type': 1, 'id': movie_id, 'editionTitle.value': '', 'editionTitle.locked': 0}
        s = get_session()
        s.put(f'{server}/library/metadata/{movie_id}', headers={'X-Plex-Token': token}, params=params)
        logger.info(f"Reset: {movie.get('title', 'Unknown')}")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for i in range(0, len(to_reset), batch_size):
            batch = to_reset[i:i+batch_size]
            futures = [ex.submit(_reset_one, m) for m in batch]
            for _ in as_completed(futures):
                _progress_step()
            logger.info(f"Reset batch {i//batch_size + 1}/{(len(to_reset)+batch_size-1)//batch_size}")

# Reset a single movie
def reset_movie(server, token, movie):
    movie_id = movie['ratingKey']
    title = movie.get('title', 'Unknown')
    
    try:
        params = {'type': 1, 'id': movie_id, 'editionTitle.value': '', 'editionTitle.locked': 0}
        session = get_session()
        session.put(f'{server}/library/metadata/{movie_id}', headers={'X-Plex-Token': token}, params=params)
        logger.info(f'Reset {title}')
        return True
    except Exception as e:
        logger.error(f"Error resetting movie {title}: {str(e)}")
        return False

# Backup metadata
def backup_metadata(server, token, backup_file):
    headers = {'X-Plex-Token': token, 'Accept': 'application/json'}
    libraries = make_request(f'{server}/library/sections', headers)['MediaContainer']['Directory']
    metadata = {}
    for lib in libraries:
        if lib.get('type') == 'movie':
            response = make_request(f"{server}/library/sections/{lib['key']}/all", headers)
            for movie in response['MediaContainer'].get('Metadata', []):
                metadata[movie['ratingKey']] = {
                    'title': movie.get('title', ''),
                    'editionTitle': movie.get('editionTitle', '')
                }

    backup_file = Path(backup_file)  # normalize in case a string is passed
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    with backup_file.open('w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Backup complete. {len(metadata)} movies saved to {backup_file}")

# Improved restore metadata function
def restore_metadata(server, token, backup_file):
    with open(backup_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    items = list(metadata.items())
    logger.info(f"Starting restore for {len(items)} movies")
    _progress_set_total(len(items))

    def _restore_one(pair):
        movie_id, meta = pair
        edition = meta.get('editionTitle', '')
        params = {'type': 1, 'id': movie_id, 'editionTitle.value': edition, 'editionTitle.locked': 1 if edition else 0}
        s = get_session()
        s.put(f'{server}/library/metadata/{movie_id}', headers={'X-Plex-Token': token}, params=params)
        _progress_step()

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_restore_one, p) for p in items]
        for _ in as_completed(futures):
            pass

    logger.info("Restore complete.")

# Main function
def main():
    (
        server,
        token,
        skip_libraries,
        modules,
        excluded_languages,
        skip_multiple_audio_tracks,
        tmdb_api_key,
        max_workers,
        batch_size
    ) = initialize_settings()
    
    parser = argparse.ArgumentParser(description='Manage Plex server movie editions')
    parser.add_argument('--all', action='store_true', help='Add edition info to all movies')
    parser.add_argument('--one', action='store_true',
                    help='Interactively search and process a single movie')
    parser.add_argument('--one-id', dest='one_id', metavar='RATINGKEY',
                        help='Process a single movie by ratingKey (non-interactive; used by GUI)')
    parser.add_argument('--reset', action='store_true', help='Reset edition info for all movies')
    parser.add_argument('--backup', action='store_true', help='Backup movie metadata')
    parser.add_argument('--restore', action='store_true', help='Restore movie metadata from backup')
    
    args = parser.parse_args()
    
    backup_file = Path(__file__).parent / 'metadata_backup' / 'metadata_backup.json'

    if args.one_id:
        ok = process_movie_by_rating_key(
            server, token, args.one_id, modules, excluded_languages, skip_multiple_audio_tracks, tmdb_api_key
        )
        logger.info('Done.' if ok else 'Failed.')
    elif args.one:
        # Interactive terminal flow
        title = input("Enter movie title to search: ").strip()
        if not title:
            logger.info("No title entered.")
            return
        matches = find_movies_by_title(server, token, title)
        if not matches:
            logger.info(f"No movies found for '{title}'.")
            return

        print(f"\nFound {len(matches)} match(es):")
        for i, m in enumerate(matches,  start=1):
            print(f"{i}. {m.get('title','?')} ({m.get('year','?')}) — {m.get('library','')}")
        sel = input("\nSelect a number (or Enter for 1): ").strip() or "1"
        try:
            idx = int(sel) - 1
            if idx < 0 or idx >= len(matches):
                raise ValueError
        except ValueError:
            print("Invalid selection.")
            return

        chosen = matches[idx]
        confirm = input(f"Process '{chosen['title']}' ({chosen.get('year','?')}) from {chosen.get('library','')}? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Cancelled.")
            return

        ok = process_movie_by_rating_key(
            server, token, chosen['ratingKey'], modules, excluded_languages, skip_multiple_audio_tracks, tmdb_api_key
        )
        logger.info('Done.' if ok else 'Failed.')

    #make if to revert
    elif args.backup:
        backup_metadata(server, token, backup_file)
        logger.info('Metadata backup completed.')
    elif args.restore:
        restore_metadata(server, token, backup_file)
        logger.info('Metadata restoration completed.')
    elif args.all:
        process_movies(
            server,
            token,
            skip_libraries,
            modules,
            excluded_languages,
            skip_multiple_audio_tracks,
            tmdb_api_key,
            max_workers,
            batch_size
        )
    elif args.reset:
        reset_movies(
            server,
            token,
            skip_libraries,
            max_workers,
            batch_size
        )
    else:
        logger.info('No action specified. Please use one of the following arguments:')
        logger.info('  --all: Add edition info to all movies')
        logger.info('  --reset: Reset edition info for all movies')
        logger.info('  --backup: Backup movie metadata')
        logger.info('  --restore: Restore movie metadata from backup')
    
    logger.info('Script execution completed.')

if __name__ == '__main__':
    main()