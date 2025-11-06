from configparser import ConfigParser
import logging
import requests

logger = logging.getLogger(__name__)

def get_Rating(movie_data, tmdb_api_key):
    config = ConfigParser()
    config.read('config/config.ini')

    rating_source = config.get('rating', 'source', fallback='imdb').lower()
    rt_type = config.get('rating', 'rotten_tomatoes_type', fallback='critic').lower()

    if rating_source == 'imdb':
        # (really TMDb vote_average, 0-10, like "7.4")
        return _get_tmdb_rating(movie_data, tmdb_api_key)

    if rating_source == 'rotten_tomatoes':
        return _get_rotten_tomatoes_rating(movie_data, rt_type)

    return None

def _get_tmdb_rating(movie_data, tmdb_api_key):
    if not tmdb_api_key:
        logger.error("TMDb API key is missing.")
        return None

    title = movie_data.get('title')
    year = movie_data.get('year')
    if not title or not year:
        return None

    url = (
        "https://api.themoviedb.org/3/search/movie"
        f"?api_key={tmdb_api_key}"
        f"&query={requests.utils.quote(title)}"
        f"&year={year}"
    )

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get('results', [])
        if results:
            rating = results[0].get('vote_average')
            if rating is not None:
                return f"{float(rating):.1f}"
    except Exception as e:
        logger.error(f"Error fetching TMDb rating for {title} ({year}): {e}")

    return None

def _format_percent(val):
    if val is None:
        return None
    try:
        num = float(val)

        # if Plex gave us 0-10 style (8.4), scale to 84
        if num <= 10:
            pct = int(round(num * 10))
        else:
            pct = int(round(num))

        return f"{pct}%"
    except Exception:
        return None

def _get_rotten_tomatoes_rating(movie_data, rt_type):
    # audience mode -> prefer audienceRating, fallback to rating
    if rt_type == 'audience':
        aud_raw = movie_data.get('audienceRating')
        formatted = _format_percent(aud_raw)
        if formatted:
            return formatted
        # fallback to critic-style (rating)
        crit_raw = movie_data.get('rating')
        return _format_percent(crit_raw)
    # critic mode (default) -> prefer rating, fallback to audienceRating
    crit_raw = movie_data.get('rating')
    formatted = _format_percent(crit_raw)
    if formatted:
        return formatted

    aud_raw = movie_data.get('audienceRating')
    return _format_percent(aud_raw)