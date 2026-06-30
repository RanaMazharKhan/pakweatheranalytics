"""Fetch weather data from Open-Meteo (free, open-source, no API key required)."""

import json
import logging
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.utils import timezone

from .models import WeatherData

logger = logging.getLogger(__name__)

ARCHIVE_API = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST_API = 'https://api.open-meteo.com/v1/forecast'
TIMEZONE = 'Asia/Karachi'
DEFAULT_DAYS = 90

CITY_COORDINATES = {
    'Lahore': (31.5497, 74.3436),
    'Karachi': (24.8607, 67.0011),
    'Islamabad': (33.6844, 73.0479),
    'Rawalpindi': (33.5651, 73.0169),
    'Faisalabad': (31.4180, 73.0790),
    'Multan': (30.1575, 71.5249),
    'Peshawar': (34.0151, 71.5249),
    'Quetta': (30.1798, 66.9750),
    'Sialkot': (32.4945, 74.5229),
    'Gujranwala': (32.1877, 74.1945),
    'Hyderabad': (25.3960, 68.3578),
    'Bahawalpur': (29.3956, 71.6836),
}

WEATHER_CODES = {
    0: 'Clear',
    1: 'Mainly Clear',
    2: 'Partly Cloudy',
    3: 'Overcast',
    45: 'Fog',
    48: 'Fog',
    51: 'Light Drizzle',
    53: 'Drizzle',
    55: 'Dense Drizzle',
    56: 'Freezing Drizzle',
    57: 'Freezing Drizzle',
    61: 'Light Rain',
    63: 'Rain',
    65: 'Heavy Rain',
    66: 'Freezing Rain',
    67: 'Freezing Rain',
    71: 'Light Snow',
    73: 'Snow',
    75: 'Heavy Snow',
    77: 'Snow Grains',
    80: 'Rain Showers',
    81: 'Rain Showers',
    82: 'Heavy Rain Showers',
    85: 'Snow Showers',
    86: 'Heavy Snow Showers',
    95: 'Thunderstorm',
    96: 'Thunderstorm with Hail',
    99: 'Thunderstorm with Hail',
}


def degrees_to_compass(degrees):
    if degrees is None:
        return 'N'
    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return directions[int((float(degrees) + 22.5) / 45) % 8]


def weather_code_to_condition(code):
    if code is None:
        return 'Clear'
    return WEATHER_CODES.get(int(code), 'Unknown')


def estimate_visibility(weather_code):
    code = int(weather_code) if weather_code is not None else 0
    if code in (45, 48):
        return 2.0
    if code in (55, 65, 82, 95, 96, 99):
        return 5.0
    if code in (3, 51, 53, 61, 63, 80, 81):
        return 8.0
    return 10.0


def _fetch_json(base_url, params):
    url = f'{base_url}?{urlencode(params)}'
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def fetch_city_weather(city, start_date, end_date):
    latitude, longitude = CITY_COORDINATES[city]
    past_days = max(1, (end_date - start_date).days + 1)
    past_days = min(past_days, 92)

    params = {
        'latitude': latitude,
        'longitude': longitude,
        'daily': ','.join([
            'temperature_2m_max',
            'temperature_2m_min',
            'temperature_2m_mean',
            'precipitation_sum',
            'wind_speed_10m_max',
            'wind_direction_10m_dominant',
            'relative_humidity_2m_mean',
            'surface_pressure_mean',
            'weather_code',
        ]),
        'timezone': TIMEZONE,
        'past_days': past_days,
        'forecast_days': 1,
    }

    data = _fetch_json(FORECAST_API, params)

    daily = data.get('daily', {})
    dates = daily.get('time', [])
    if not dates:
        return []

    records = []
    for index, record_date in enumerate(dates):
        weather_code = daily.get('weather_code', [None] * len(dates))[index]
        records.append({
            'date': date.fromisoformat(record_date),
            'city': city,
            'temperature_max': _safe_float(daily.get('temperature_2m_max', [])[index]),
            'temperature_min': _safe_float(daily.get('temperature_2m_min', [])[index]),
            'temperature_avg': _safe_float(daily.get('temperature_2m_mean', [])[index]),
            'humidity': _safe_float(daily.get('relative_humidity_2m_mean', [])[index], 50),
            'precipitation': _safe_float(daily.get('precipitation_sum', [])[index]),
            'wind_speed': _safe_float(daily.get('wind_speed_10m_max', [])[index]),
            'wind_direction': degrees_to_compass(daily.get('wind_direction_10m_dominant', [])[index]),
            'pressure': _safe_float(daily.get('surface_pressure_mean', [])[index], 1013),
            'visibility': estimate_visibility(weather_code),
            'weather_condition': weather_code_to_condition(weather_code),
        })
    return records


def _safe_float(value, default=0.0):
    if value is None:
        return default
    return round(float(value), 1)


def sync_weather_data(days=DEFAULT_DAYS, cities=None):
    """Fetch weather from Open-Meteo and store in the database."""
    cities = cities or list(CITY_COORDINATES.keys())
    today = timezone.localdate()
    end_date = today
    start_date = today - timedelta(days=days - 1)

    total_saved = 0
    errors = []

    for city in cities:
        try:
            records = fetch_city_weather(city, start_date, end_date)
            if records:
                import pandas as pd
                total_saved += WeatherData.import_from_dataframe(pd.DataFrame(records))
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            logger.exception('Failed to fetch weather for %s', city)
            errors.append(f'{city}: {exc}')

    return {
        'saved': total_saved,
        'cities': len(cities),
        'start_date': start_date,
        'end_date': end_date,
        'errors': errors,
    }


def needs_weather_sync(max_age_days=1):
    count = WeatherData.objects.count()
    if count == 0:
        return True, DEFAULT_DAYS

    latest = WeatherData.objects.order_by('-date').values_list('date', flat=True).first()
    if not latest:
        return True, DEFAULT_DAYS

    days_behind = (timezone.localdate() - latest).days
    if days_behind >= max_age_days:
        return True, min(max(days_behind + 7, 14), DEFAULT_DAYS)

    return False, 0


import threading
import os
from django.conf import settings
import pandas as pd

sync_lock = threading.Lock()
is_syncing = False

def ensure_weather_data(force=False):
    """Load weather data if the database is empty or outdated."""
    if WeatherData.objects.count() == 0:
        seed_offline_data()
    should_sync, days = needs_weather_sync()
    if force:
        return sync_weather_data(days=DEFAULT_DAYS)
    if should_sync:
        return sync_weather_data(days=days)
    return None

def seed_offline_data():
    try:
        csv_path = os.path.join(settings.BASE_DIR, 'data', 'sample_weather_data.csv')
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            df['date'] = pd.to_datetime(df['date']).dt.date
            count = WeatherData.import_from_dataframe(df)
            logger.info("Successfully seeded database with %d records of offline sample weather data.", count)
            return True
    except Exception as e:
        logger.exception("Failed to seed database with offline sample weather data: %s", e)
    return False

def ensure_weather_data_async():
    """Start weather synchronization in a background thread to prevent blocking web requests."""
    global is_syncing
    
    if WeatherData.objects.count() == 0:
        seed_offline_data()
        
    if is_syncing:
        logger.info("Weather data sync is already running in background, skipping thread spawn.")
        return
        
    try:
        should_sync, days = needs_weather_sync()
        if should_sync:
            def run_sync():
                global is_syncing
                with sync_lock:
                    is_syncing = True
                    try:
                        sync_weather_data(days=days)
                    finally:
                        is_syncing = False
                        
            thread = threading.Thread(target=run_sync)
            thread.daemon = True
            thread.start()
            logger.info("Started background weather sync thread for %d days", days)
    except Exception:
        logger.exception("Failed to start background weather sync thread")
