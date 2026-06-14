import json
import os
import re
import difflib
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
from langchain_core.tools import tool

# Import database caching helpers
from database import (
    get_route_cache, set_route_cache,
    get_delay_cache, set_delay_cache,
    get_schedule_cache, set_schedule_cache
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def load_stations():
    # Locates stations.json in the current data/ folder, root, or parent folders
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stations.json"),
        os.path.join(parent, "data", "stations.json"),
        os.path.join(parent, "stations.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "stations.json")
    ]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("Could not locate stations.json in any expected path.")

def get_mock_file(filename):
    # Search for mock files in local directories
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder_name in ("url responses", "url_responses"):
        path = os.path.join(parent, folder_name, filename)
        if os.path.exists(path):
            return path
    return None

def fuzzy_match_station(query, stations):
    query_lower = query.lower().strip()
    if not query_lower:
        return None
        
    # 1. Exact code match
    for st in stations:
        if st.get("code", "").lower() == query_lower:
            return st
            
    # 2. Exact name match
    for st in stations:
        name = st.get("name") or ""
        if name.lower() == query_lower:
            return st
            
    # 3. Exact city_village match — collect ALL matches, then pick the best one
    #    Prefer stations whose name also contains the query (e.g., "SECUNDERABAD JN" over "ALWAL")
    city_matches = []
    for st in stations:
        city = st.get("city_village") or ""
        if city.lower() == query_lower:
            name = (st.get("name") or "").lower()
            # Boost score if the station name itself contains the query
            if query_lower in name:
                city_matches.append((2.0, st))  # High priority: name contains query
            else:
                city_matches.append((1.0, st))  # Lower priority: only city matches
    
    if city_matches:
        city_matches.sort(key=lambda x: x[0], reverse=True)
        return city_matches[0][1]
            
    # 4. Substring/prefix match — name matches always score higher than city matches
    substring_matches = []
    for st in stations:
        name = st.get("name") or ""
        city = st.get("city_village") or ""
        name_lower = name.lower()
        city_lower = city.lower()
        
        # Check name prefix (highest priority)
        if name_lower.startswith(query_lower):
            score = 1.0 - (len(name_lower) - len(query_lower)) * 0.01
            substring_matches.append((score, st))
        # Check name substring (high priority)
        elif query_lower in name_lower:
            score = 0.85 - (len(name_lower) - len(query_lower)) * 0.01
            substring_matches.append((score, st))
        # Check city prefix (medium priority)
        elif city_lower.startswith(query_lower):
            score = 0.7 - (len(city_lower) - len(query_lower)) * 0.01
            substring_matches.append((score, st))
        # Check city substring (lowest priority)
        elif query_lower in city_lower:
            score = 0.6 - (len(city_lower) - len(query_lower)) * 0.01
            substring_matches.append((score, st))
            
    if substring_matches:
        substring_matches.sort(key=lambda x: x[0], reverse=True)
        return substring_matches[0][1]
        
    # 5. Fallback to full SequenceMatcher
    # Collect all candidates, then tiebreak: prefer stations whose NAME contains the query
    candidates = []
    for st in stations:
        name = (st.get("name") or "").lower()
        city = (st.get("city_village") or "").lower()
        
        name_score = difflib.SequenceMatcher(None, query_lower, name).ratio() if name else 0.0
        city_score = difflib.SequenceMatcher(None, query_lower, city).ratio() if city else 0.0
        raw_score = max(name_score, city_score)
        
        if raw_score > 0.5:
            # Tiebreaker: if the station NAME itself contains the query (fuzzy), boost it
            # This ensures "SECUNDERABAD JN" beats "ALWAL" for query "secundrabad"
            name_contains_query = query_lower[:4] in name  # first 4 chars as quick check
            boost = 0.15 if name_contains_query else 0.0
            candidates.append((raw_score + boost, st))
    
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None


def parse_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # 1. Check relative weekdays (e.g. Wednesday, next wednesday)
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    cleaned = date_str.lower().strip()
    
    if cleaned == "today":
        return datetime.now()
    elif cleaned == "tomorrow":
        return datetime.now() + timedelta(days=1)
        
    cleaned_weekday = cleaned.replace("next", "").strip()
    if cleaned_weekday in weekdays:
        target_weekday = weekdays.index(cleaned_weekday)
        today = datetime.now()
        days_ahead = target_weekday - today.weekday()
        if days_ahead <= 0:  # Already happened this week, or is today
            days_ahead += 7
        return today + timedelta(days=days_ahead)
        
    # 2. Standard format parsing
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def parse_route_html(html, target_date_obj=None):
    soup = BeautifulSoup(html, "html.parser")
    trains = []
    
    rows = soup.select("tr[data-train]")
    for row in rows:
        data_str = row.get("data-train")
        if not data_str:
            continue
        try:
            train_data = json.loads(data_str)
        except json.JSONDecodeError:
            continue
            
        classes = []
        class_links = row.select("a.cavlink")
        for link in class_links:
            ettav_str = link.get("data-ettav")
            if ettav_str:
                try:
                    ettav_data = json.loads(ettav_str)
                    if "c" in ettav_data:
                        classes.append(ettav_data["c"])
                except json.JSONDecodeError:
                    pass
            if not classes and link.get_text():
                classes.append(link.get_text().strip())
                
        if not classes:
            td_classes = row.select_one("td.wd191, td.bold.wd191")
            if td_classes:
                classes = [a.get_text().strip() for a in td_classes.find_all('a')]
                
        classes = list(dict.fromkeys([c for c in classes if c]))
        
        # Extract train slug from href
        slug = ""
        for a in row.select("a[href*='/train/']"):
            href = a.get("href", "")
            match = re.match(r'/train/([^/]+)/schedule', href)
            if match:
                slug = match.group(1)
                break

        train_info = {
            "train_number": train_data.get("num", ""),
            "train_name": train_data.get("name", ""),
            "source": train_data.get("s", ""),
            "depart_time": train_data.get("st", ""),
            "destination": train_data.get("d", ""),
            "arrival_time": train_data.get("dt", ""),
            "travel_time": train_data.get("tt", ""),
            "running_days": train_data.get("dy", ""),
            "classes": classes,
            "train_slug": slug
        }
        
        if target_date_obj:
            etrain_idx = (target_date_obj.weekday() + 2) % 7
            dy_str = train_info["running_days"]
            if len(dy_str) == 7:
                train_info["runs_on_date"] = (dy_str[etrain_idx] == "1")
            else:
                train_info["runs_on_date"] = True
        else:
            train_info["runs_on_date"] = True
            
        trains.append(train_info)
        
    return trains

def fallback_pandas_route(html):
    try:
        dfs = pd.read_html(html)
    except Exception:
        return []
        
    trains = []
    for df in dfs:
        cols = [str(c).lower() for c in df.columns]
        if len(df.columns) >= 7:
            for idx, row in df.iterrows():
                row_vals = [str(val).strip() for val in row.values]
                if not row_vals[0].isdigit():
                    continue
                classes_text = row_vals[-1]
                classes = [c.strip() for c in re.split(r'[\s,&|]+', classes_text) if c.strip()]
                
                train_info = {
                    "train_number": row_vals[0],
                    "train_name": row_vals[1],
                    "source": row_vals[2],
                    "depart_time": row_vals[3],
                    "destination": row_vals[4],
                    "arrival_time": row_vals[5],
                    "travel_time": row_vals[6],
                    "running_days": "1111111",
                    "classes": classes,
                    "runs_on_date": True
                }
                trains.append(train_info)
            if trains:
                break
    return trains

def parse_delay_html(html):
    soup = BeautifulSoup(html, "html.parser")
    delays = {}
    
    anchors = soup.find_all("a", class_="runStatStn")
    for a in anchors:
        href = a.get("href", "")
        code = href.replace("#", "").strip()
        if not code:
            continue
        text = a.get_text(separator=" ", strip=True)
        match = re.search(r'Avg\.\s*Delay:\s*([\d\.]+)\s*Min', text, re.IGNORECASE)
        if match:
            try:
                delays[code] = float(match.group(1))
            except ValueError:
                pass
                
    if not delays:
        for script in soup.find_all("script"):
            if script.string and "et.rsStat.primaryData" in script.string:
                match = re.search(r'et\.rsStat\.primaryData\s*=\s*(\[.*?\]);', script.string, re.DOTALL)
                if match:
                    array_str = match.group(1)
                    stn_matches = re.findall(r"\[\s*'([A-Z]{2,6})'\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d\.]+)\s*\]", array_str)
                    for stn_code, avg_delay in stn_matches:
                        try:
                            delays[stn_code] = float(avg_delay)
                        except ValueError:
                            pass
                    if delays:
                        break
                        
    return delays


def parse_delay_html_detailed(html):
    soup = BeautifulSoup(html, "html.parser")
    stations = []
    
    # Try to extract train name and route if available
    train_name = ""
    train_route = ""
    
    title_td = soup.find("td", class_="bx3_bgd")
    if title_td:
        bold_tag = title_td.find("b")
        if bold_tag:
            train_name = bold_tag.get_text(strip=True)
        route_span = title_td.find("span", class_="mdtext")
        if route_span:
            train_route = route_span.get_text(strip=True)
    else:
        # Fallback to title tag
        title = soup.find("title")
        if title:
            title_text = title.get_text(strip=True)
            match = re.search(r'Running History of\s*(.*?)\s*for', title_text, re.IGNORECASE)
            if match:
                train_name = match.group(1).strip()

    anchors = soup.find_all("a", class_="runStatStn")
    for a in anchors:
        href = a.get("href", "")
        code = href.replace("#", "").strip()
        if not code:
            continue
            
        first_div = a.find("div")
        if first_div:
            div_text = first_div.get_text(separator=" ", strip=True)
            div_text = re.sub(r'Avg\.\s*Delay:.*$', '', div_text, flags=re.IGNORECASE).strip()
            match_name = re.match(r'^(.*?)\s*\(\s*([A-Z0-9]+)\s*\)', div_text)
            if match_name:
                name = match_name.group(1).strip()
                code = match_name.group(2).strip()
            else:
                name = div_text
        else:
            name = code
            
        text = a.get_text(separator=" ", strip=True)
        match_delay = re.search(r'Avg\.\s*Delay:\s*([\d\.]+)\s*Min', text, re.IGNORECASE)
        avg_delay = None
        if match_delay:
            try:
                avg_delay = float(match_delay.group(1))
            except ValueError:
                pass
                
        # Parse the color percentages
        percentages = {"green": 0.0, "yellow": 0.0, "red": 0.0, "grey": 0.0}
        bar_div = a.find("div", class_="nowrap") or a.find("div", class_="nowrap fullw")
        if bar_div:
            color_divs = bar_div.find_all("div", recursive=False)
            for cd in color_divs:
                style = cd.get("style", "")
                bg_match = re.search(r'background-color:\s*(#[0-9a-fA-F]+|[a-zA-Z]+)', style)
                width_match = re.search(r'width:\s*([\-\d\.]+)%', style)
                if bg_match and width_match:
                    bg_color = bg_match.group(1).lower()
                    try:
                        width_val = max(0.0, float(width_match.group(1)))
                    except ValueError:
                        width_val = 0.0
                        
                    if bg_color in ("#008000", "green"):
                        percentages["green"] = width_val
                    elif bg_color in ("#ffa500", "orange", "yellow"):
                        percentages["yellow"] = width_val
                    elif bg_color in ("#ff0000", "red"):
                        percentages["red"] = width_val
                    elif bg_color in ("#808080", "grey", "gray"):
                        percentages["grey"] = width_val
                        
        stations.append({
            "code": code,
            "name": name,
            "avg_delay": avg_delay,
            "percentages": percentages
        })
        
    return {
        "train_name": train_name,
        "train_route": train_route,
        "stations": stations
    }

def parse_schedule_html(html):
    soup = BeautifulSoup(html, "html.parser")
    stops = []
    
    rows = soup.select("#sublowerdata table tr")
    for row in rows:
        stn_div = row.find("div", class_="fixwelps")
        if not stn_div:
            continue
            
        tds = row.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
            
        s_no_div = tds[0].find("div")
        s_no = s_no_div.get_text(strip=True) if s_no_div else ""
        
        code_small = tds[0].find("small")
        code = code_small.get_text(strip=True) if code_small else ""
        
        stn_name = stn_div.get_text(strip=True)
        
        dist_div = tds[2].find("div", class_="fixw70")
        distance = dist_div.get_text(strip=True) if dist_div else ""
        
        plat_small = tds[2].find("small")
        platform = ""
        if plat_small:
            plat_text = plat_small.get_text(" ", strip=True)
            plat_match = re.search(r'Platform:\s*(\d+)', plat_text, re.IGNORECASE)
            if plat_match:
                platform = plat_match.group(1)
                
        timing_divs = tds[4].find_all("div")
        arrival = timing_divs[0].get_text(strip=True) if len(timing_divs) > 0 else ""
        departure = timing_divs[1].get_text(strip=True) if len(timing_divs) > 1 else ""
        
        stops.append({
            "stop_number": s_no,
            "station_code": code,
            "station_name": stn_name,
            "distance": distance,
            "platform": platform,
            "arrival_time": arrival,
            "departure_time": departure
        })
        
    return stops

@tool
def lookup_station_code(station_name: str) -> str:
    """
    Look up the exact station name and code for a given query (station name or city/village).
    Fuzzy matches the input against names and city/village details in stations.json.
    """
    try:
        stations = load_stations()
    except Exception as e:
        return f"Error loading stations list: {str(e)}"
        
    match = fuzzy_match_station(station_name, stations)
    if match:
        return f"{match['name']} | Code: {match['code']}"
    return f"No station found matching '{station_name}'"

@tool
def fetch_trains_between_stations(source_code: str, destination_code: str, date: str = None) -> str:
    """
    Fetch trains running between source_code and destination_code.
    Optionally, a date (e.g., YYYY-MM-DD or DD-MM-YYYY) can be provided to strictly filter
    trains that run on that specific day of the week.
    """
    source_code = source_code.upper().strip()
    destination_code = destination_code.upper().strip()
    
    # Parse date if provided
    target_date = None
    date_param = None
    if date:
        target_date = parse_date(date)
        if target_date:
            date_param = target_date.strftime("%Y%m%d")
        else:
            return f"Error: Invalid date format '{date}'. Please use YYYY-MM-DD or DD-MM-YYYY."
            
    # Cache key
    cache_key = f"{source_code}-{destination_code}"
    if date_param:
        cache_key += f"-{date_param}"
        
    # Check cache
    cached_data = get_route_cache(cache_key)
    if cached_data is not None:
        return json.dumps(cached_data)
        
    # Scrape URL
    url = f"https://etrain.info/trains/{source_code}-to-{destination_code}"
    if date_param:
        url += f"?date={date_param}"
        
    html_content = None
    
    # Check for local mock files if codes match our local blueprints
    if source_code == "VSKP" and destination_code == "TNM" and not date_param:
        mock_path = get_mock_file("station to station trains data.txt")
        if mock_path:
            with open(mock_path, "r", encoding="utf-8") as f:
                content = f.read()
                html_start = content.find("<!DOCTYPE")
                html_content = content[html_start:] if html_start != -1 else content
                
    elif source_code == "DVD" and destination_code == "TPTY" and date_param == "20260626":
        mock_path = get_mock_file("station to station with date.txt")
        if mock_path:
            with open(mock_path, "r", encoding="utf-8") as f:
                content = f.read()
                html_start = content.find("<!DOCTYPE")
                html_content = content[html_start:] if html_start != -1 else content
                
    # If not loaded from mock, fetch via HTTP requests
    if not html_content:
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                html_content = response.text
            else:
                return f"Error fetching trains: HTTP {response.status_code}"
        except Exception as e:
            # Fallback to local files if request fails
            if source_code == "VSKP" and destination_code == "TNM":
                mock_path = get_mock_file("station to station trains data.txt")
                if mock_path:
                    with open(mock_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        html_start = content.find("<!DOCTYPE")
                        html_content = content[html_start:] if html_start != -1 else content
            elif source_code == "DVD" and destination_code == "TPTY":
                mock_path = get_mock_file("station to station with date.txt")
                if mock_path:
                    with open(mock_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        html_start = content.find("<!DOCTYPE")
                        html_content = content[html_start:] if html_start != -1 else content
            
            if not html_content:
                return f"Error fetching trains from etrain.info: {str(e)}"
                
    # Parse HTML
    trains = parse_route_html(html_content, target_date)
    if not trains:
        trains = fallback_pandas_route(html_content)
        
    # Apply strict date filtering if date was provided
    if target_date:
        trains = [t for t in trains if t.get("runs_on_date", True)]
        
    # Cache and return
    set_route_cache(cache_key, trains)
    return json.dumps(trains)

def resolve_history_url(train_number: str, duration: str) -> str:
    """
    Resolves the canonical etrain history URL for a train number.
    Ensures that duration query parameters are not stripped by redirects.
    """
    train_number = train_number.strip()
    
    # If the input is already a canonical train slug (contains letters/hyphens), return it directly
    if not train_number.isdigit():
        return f"https://etrain.info/train/{train_number}/history?d={duration}"
        
    cache_key = f"resolved-url-{train_number}"
    
    # Check cache
    cached_url = get_delay_cache(cache_key)
    if cached_url:
        resolved_url = cached_url
    else:
        initial_url = f"https://etrain.info/train/{train_number}/history"
        try:
            r = requests.get(initial_url, headers=HEADERS, allow_redirects=True, timeout=10)
            resolved_url = r.url
            set_delay_cache(cache_key, resolved_url)
        except Exception:
            resolved_url = initial_url
        
    # Append/replace the duration query parameter on the resolved canonical URL
    if "?" in resolved_url:
        resolved_url = re.sub(r'[\?&]d=[^&]*', '', resolved_url)
        resolved_url += f"&d={duration}" if "?" in resolved_url else f"?d={duration}"
    else:
        resolved_url += f"?d={duration}"
        
    return resolved_url

@tool
def fetch_train_delay_history(train_number: str, duration: str = "1y") -> str:
    """
    Fetch the average running delay times in minutes for a given train_number over the specified duration (default '1y').
    Returns a JSON string mapping station codes to average delay minutes.
    """
    train_number = train_number.strip()
    duration = duration.strip()
    cache_key = f"{train_number}-{duration}"
    
    # Check cache
    cached_data = get_delay_cache(cache_key)
    if cached_data is not None:
        return json.dumps(cached_data)
        
    html_content = None
    
    # Check for local mock files if codes match our local blueprints
    if train_number == "22603" and duration == "1y":
        mock_path = get_mock_file("history-1y.txt")
        if mock_path:
            with open(mock_path, "r", encoding="utf-8") as f:
                content = f.read()
                html_start = content.find("<!DOCTYPE")
                html_content = content[html_start:] if html_start != -1 else content
                
    # Scrape if not loaded from mock
    if not html_content:
        url = resolve_history_url(train_number, duration)
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                html_content = response.text
            else:
                return f"Error fetching delay history: HTTP {response.status_code}"
        except Exception as e:
            # Fallback to local files if request fails
            if train_number == "22603":
                mock_path = get_mock_file("history-1y.txt")
                if mock_path:
                    with open(mock_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        html_start = content.find("<!DOCTYPE")
                        html_content = content[html_start:] if html_start != -1 else content
            if not html_content:
                return f"Error fetching delay history from etrain.info: {str(e)}"
                
    # Parse HTML
    delays = parse_delay_html(html_content)
    
    # Cache and return
    set_delay_cache(cache_key, delays)
    return json.dumps(delays)


def fetch_train_delay_history_detailed(train_number: str, duration: str = "1y") -> dict:
    """
    Fetch the detailed average running delay times and station names for a given train_number over the specified duration.
    Returns a dictionary with 'train_name', 'train_route', and 'stations' list.
    """
    train_number = train_number.strip()
    duration = duration.strip()
    cache_key = f"detailed-{train_number}-{duration}"
    
    # Check cache
    cached_data = get_delay_cache(cache_key)
    if cached_data is not None:
        return cached_data
        
    html_content = None
    
    # Check for local mock files if codes match our local blueprints
    if train_number == "22603" and duration == "1y":
        mock_path = get_mock_file("history-1y.txt")
        if mock_path:
            with open(mock_path, "r", encoding="utf-8") as f:
                content = f.read()
                html_start = content.find("<!DOCTYPE")
                html_content = content[html_start:] if html_start != -1 else content
                
    # Scrape if not loaded from mock
    if not html_content:
        url = resolve_history_url(train_number, duration)
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                html_content = response.text
            else:
                return {"error": f"Error fetching delay history: HTTP {response.status_code}"}
        except Exception as e:
            # Fallback to local files if request fails
            if train_number == "22603":
                mock_path = get_mock_file("history-1y.txt")
                if mock_path:
                    with open(mock_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        html_start = content.find("<!DOCTYPE")
                        html_content = content[html_start:] if html_start != -1 else content
            if not html_content:
                return {"error": f"Error fetching delay history from etrain.info: {str(e)}"}
                
    # Parse HTML
    result = parse_delay_html_detailed(html_content)
    
    # Cache and return (if not empty/error)
    if result and result.get("stations"):
        set_delay_cache(cache_key, result)
        
    return result

@tool
def fetch_train_schedule(train_number: str) -> str:
    """
    Fetch the list of stops (schedule) for a given train_number.
    Returns a JSON string containing stops, platform, distance, arrival/departure times.
    """
    train_number = train_number.strip()
    
    # Check cache
    cached_data = get_schedule_cache(train_number)
    if cached_data is not None:
        return json.dumps(cached_data)
        
    url = f"https://etrain.info/train/{train_number}/schedule"
    html_content = None
    
    # Check for local mock files if codes match our local blueprints
    if train_number == "22603":
        mock_path = get_mock_file("schedule of train.txt")
        if mock_path:
            with open(mock_path, "r", encoding="utf-8") as f:
                content = f.read()
                html_start = content.find("<!DOCTYPE")
                html_content = content[html_start:] if html_start != -1 else content
                
    # Scrape if not loaded from mock
    if not html_content:
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                html_content = response.text
            else:
                return f"Error fetching train schedule: HTTP {response.status_code}"
        except Exception as e:
            # Fallback to local files if request fails
            if train_number == "22603":
                mock_path = get_mock_file("schedule of train.txt")
                if mock_path:
                    with open(mock_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        html_start = content.find("<!DOCTYPE")
                        html_content = content[html_start:] if html_start != -1 else content
            if not html_content:
                return f"Error fetching train schedule from etrain.info: {str(e)}"
                
    # Parse HTML
    stops = parse_schedule_html(html_content)
    
    # Cache and return
    set_schedule_cache(train_number, stops)
    return json.dumps(stops)


def parse_travel_time_str(tt_str):
    # e.g., "15:46H" or "15:46" or "15h 46m"
    tt_str = tt_str.upper().strip()
    match = re.match(r'(\d+):(\d+)', tt_str)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    match = re.match(r'(\d+)\s*H\s*(\d+)\s*M', tt_str)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    hours = 0
    minutes = 0
    h_match = re.search(r'(\d+)\s*H', tt_str)
    if h_match:
        hours = int(h_match.group(1))
    m_match = re.search(r'(\d+)\s*M', tt_str)
    if m_match:
        minutes = int(m_match.group(1))
    if hours or minutes:
        return hours * 60 + minutes
    if ":" in tt_str:
        parts = tt_str.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    return 0


def format_minutes_to_hm(minutes):
    h = minutes // 60
    m = minutes % 60
    if h > 0:
        return f"{h} hours {m} minutes"
    return f"{m} minutes"


@tool
def fetch_route_recommendations(source: str, destination: str, date: str = None, depart_after: str = None, arrive_before: str = None) -> str:
    """
    Fetch all trains between source and destination, retrieve delay history for each,
    compute True Travel Times, and rank them into Fastest, Most Reliable, and Balanced.
    Accepts station names (e.g. "Rajahmundry") or codes (e.g. "RJY") and resolves them internally.
    Optionally, filter by depart_after (e.g., '18:00') and arrive_before (e.g., '08:00').
    """
    try:
        stations = load_stations()
    except Exception as e:
        return json.dumps({"error": f"Failed to load stations data: {str(e)}"})
        
    # Resolve source
    source_clean = source.strip()
    source_match = fuzzy_match_station(source_clean, stations)
    if not source_match:
        return json.dumps({"error": f"Could not find station matching '{source}'."})
    source_code = source_match["code"]
    source_name = source_match["name"]
    
    # Resolve destination
    dest_clean = destination.strip()
    dest_match = fuzzy_match_station(dest_clean, stations)
    if not dest_match:
        return json.dumps({"error": f"Could not find station matching '{destination}'."})
    destination_code = dest_match["code"]
    destination_name = dest_match["name"]
    
    # Cache key for recommendations to avoid heavy live scraping on repeats
    cache_key = f"rec-{source_code}-{destination_code}"
    if date:
        cache_key += f"-{date}"
    if depart_after:
        cache_key += f"-dep{depart_after.replace(':', '')}"
    if arrive_before:
        cache_key += f"-arr{arrive_before.replace(':', '')}"
        
    cached_res = get_route_cache(cache_key)
    if cached_res is not None:
        return json.dumps(cached_res)
        
    # 1. Fetch trains between stations
    trains_json = fetch_trains_between_stations.func(source_code, destination_code, date)
    if not trains_json or not trains_json.strip().startswith("["):
        return json.dumps({"error": trains_json})
    try:
        trains = json.loads(trains_json)
    except Exception as e:
        return json.dumps({"error": f"Failed to parse trains: {str(e)}"})
        
    if not trains:
        return json.dumps({"error": f"No trains found between {source_code} and {destination_code}."})
        
    if isinstance(trains, dict) and "error" in trains:
        return trains_json
        
    # Apply time constraints filter if provided
    if depart_after or arrive_before:
        filtered = []
        for train in trains:
            dep_time = train.get("depart_time", "").strip()
            arr_time = train.get("arrival_time", "").strip()
            
            matches = True
            if depart_after and dep_time < depart_after:
                matches = False
            if arrive_before and arr_time > arrive_before:
                matches = False
            if matches:
                filtered.append(train)
        if not filtered:
            return json.dumps({"error": f"No trains found between {source_name} and {destination_name} on {date or 'any date'} matching constraints: departing after {depart_after or 'any time'} and arriving before {arrive_before or 'any time'}."})
        trains = filtered
        
    # Pre-parse scheduled travel time for all trains to allow sorting
    for train in trains:
        sched_str = train.get("travel_time", "0:00")
        train["sched_mins"] = parse_travel_time_str(sched_str)
        
    # Sort trains by scheduled travel time and limit to the top 5 fastest to speed up scraping
    trains_sorted = sorted(trains, key=lambda x: x.get("sched_mins", 9999))
    trains_to_analyze = trains_sorted[:5]
    
    from concurrent.futures import ThreadPoolExecutor
 
    def get_train_delay_info(train):
        train_num = train.get("train_number")
        if not train_num:
            return None
            
        # 2. Fetch delay history - use train_slug if available to avoid redirects
        train_ident = train.get("train_slug") or train_num
        delay_json = fetch_train_delay_history.func(train_ident, "1y")
        try:
            delays = json.loads(delay_json)
        except Exception:
            delays = {}
            
        # Get delay at the train's actual destination code for this search segment (e.g. RU instead of global TPTY)
        train_dest = train.get("destination", destination_code).upper().strip()
        avg_delay = delays.get(train_dest, 0.0)
        
        # Parse scheduled travel time
        sched_str = train.get("travel_time", "0:00")
        sched_mins = train.get("sched_mins", 0)
        
        # Calculate True Travel Time
        true_mins = sched_mins + int(avg_delay)
        
        return {
            "train_number": train_num,
            "train_name": train.get("train_name", ""),
            "source": train.get("source", ""),
            "depart_time": train.get("depart_time", ""),
            "destination": train.get("destination", ""),
            "arrival_time": train.get("arrival_time", ""),
            "scheduled_travel_time_mins": sched_mins,
            "scheduled_travel_time_str": format_minutes_to_hm(sched_mins),
            "avg_delay_at_destination_mins": avg_delay,
            "true_travel_time_mins": true_mins,
            "true_travel_time_str": format_minutes_to_hm(true_mins),
            "classes": train.get("classes", []),
            "runs_on_date": train.get("runs_on_date", True)
        }
 
    with ThreadPoolExecutor(max_workers=len(trains_to_analyze) or 1) as executor:
        results = executor.map(get_train_delay_info, trains_to_analyze)
 
    processed_trains = [r for r in results if r is not None]
        
    if not processed_trains:
        return json.dumps({"error": "No valid train data processed."})
        
    # 3. Categorize recommendations
    # Sort all trains by true travel time (ascending)
    by_true_time = sorted(processed_trains, key=lambda x: x["true_travel_time_mins"])
    # Sort all trains by delay (ascending)
    by_delay = sorted(processed_trains, key=lambda x: x["avg_delay_at_destination_mins"])
    
    fastest = by_true_time[0]
    most_reliable = by_delay[0]
    
    options = {}
    options["fastest"] = fastest
    options["most_reliable"] = most_reliable
    
    # Balanced option:
    # We want a train that is different from both if possible.
    selected_nums = {fastest["train_number"], most_reliable["train_number"]}
    candidates = [t for t in processed_trains if t["train_number"] not in selected_nums]
    
    if candidates:
        # Sort candidates by True Travel Time and pick the best one
        candidates = sorted(candidates, key=lambda x: x["true_travel_time_mins"])
        options["balanced"] = candidates[0]
    else:
        # If no distinct candidates, pick the second best train by True Travel Time or fallback
        other_trains = [t for t in processed_trains if t["train_number"] != fastest["train_number"]]
        if other_trains:
            options["balanced"] = other_trains[0]
        else:
            options["balanced"] = fastest
            
    result = {
        "source_station": source_code,
        "destination_station": destination_code,
        "all_trains": processed_trains,
        "recommendations": {
            "fastest": {
                "train_number": options["fastest"]["train_number"],
                "train_name": options["fastest"]["train_name"],
                "scheduled_travel_time": options["fastest"]["scheduled_travel_time_str"],
                "avg_delay": f"{options['fastest']['avg_delay_at_destination_mins']} minutes",
                "true_travel_time": options["fastest"]["true_travel_time_str"],
                "depart_time": options["fastest"]["depart_time"],
                "arrival_time": options["fastest"]["arrival_time"],
                "rationale": f"It has the shortest true travel time of {options['fastest']['true_travel_time_str']} (Scheduled: {options['fastest']['scheduled_travel_time_str']} + Avg Delay at destination: {options['fastest']['avg_delay_at_destination_mins']} mins)."
            },
            "most_reliable": {
                "train_number": options["most_reliable"]["train_number"],
                "train_name": options["most_reliable"]["train_name"],
                "scheduled_travel_time": options["most_reliable"]["scheduled_travel_time_str"],
                "avg_delay": f"{options['most_reliable']['avg_delay_at_destination_mins']} minutes",
                "true_travel_time": options["most_reliable"]["true_travel_time_str"],
                "depart_time": options["most_reliable"]["depart_time"],
                "arrival_time": options["most_reliable"]["arrival_time"],
                "rationale": f"It has the lowest average delay at the destination station of only {options['most_reliable']['avg_delay_at_destination_mins']} minutes, making the true travel time {options['most_reliable']['true_travel_time_str']}."
            },
            "balanced": {
                "train_number": options["balanced"]["train_number"],
                "train_name": options["balanced"]["train_name"],
                "scheduled_travel_time": options["balanced"]["scheduled_travel_time_str"],
                "avg_delay": f"{options['balanced']['avg_delay_at_destination_mins']} minutes",
                "true_travel_time": options["balanced"]["true_travel_time_str"],
                "depart_time": options["balanced"]["depart_time"],
                "arrival_time": options["balanced"]["arrival_time"],
                "rationale": f"It offers a balanced alternative with a scheduled travel time of {options['balanced']['scheduled_travel_time_str']}, an average delay of {options['balanced']['avg_delay_at_destination_mins']} minutes, and a true travel time of {options['balanced']['true_travel_time_str']}."
            }
        }
    }
    
    set_route_cache(cache_key, result)
    return json.dumps(result)


def parse_train_schedule_detailed(html):
    soup = BeautifulSoup(html, "html.parser")
    
    train_name = ""
    train_number = ""
    route = ""
    running_days = []
    classes = []
    train_type = ""
    zone = ""
    arp = ""
    
    # 1. Metadata
    title_td = soup.find("td", class_="bx3_bgd")
    if title_td:
        bold_tag = title_td.find("b")
        if bold_tag:
            title_text = bold_tag.get_text(strip=True)
            m = re.search(r'(.*?)\s*\(\s*(\d+)\s*\)', title_text)
            if m:
                train_name = m.group(1).strip()
                train_number = m.group(2).strip()
            else:
                train_name = title_text
        route_span = title_td.find("span", class_="mdtext")
        if route_span:
            route = route_span.get_text(strip=True)
            
    metadata_table = soup.find("table", class_="nocps fullw bx3s trnd5")
    if metadata_table:
        rows = metadata_table.find_all("tr")
        for r in rows:
            text = r.get_text(separator=" ", strip=True)
            if "Running Days:" in text:
                days_part = text.split("Running Days:")[1].strip()
                running_days = [d.strip() for d in re.split(r'[\s,&|]+', days_part) if d.strip()]
            if "Available Classes:" in text:
                classes_part = text.split("Available Classes:")[1].strip()
                classes = [c.strip() for c in re.split(r'[\s,&|]+', classes_part) if c.strip()]
            
            tds = r.find_all("td")
            for td in tds:
                td_text = td.get_text(strip=True)
                if td_text.startswith("Type:"):
                    train_type = td_text.split("Type:")[1].strip()
                elif td_text.startswith("Zone:"):
                    zone = td_text.split("Zone:")[1].strip()
                elif td_text.startswith("ARP:"):
                    arp = td_text.split("ARP:")[1].strip()

    # 2. Rake Composition
    rake_composition = []
    rake_div = soup.find("div", class_="fs9 pdud2")
    if rake_div:
        coaches = rake_div.find_all("div", class_="inlineblock")
        for coach in coaches:
            spans = coach.find_all("span")
            coach_div = coach.find("div", class_="rake")
            
            idx = ""
            code = ""
            name = ""
            rake_class = ""
            
            if len(spans) >= 1:
                idx = spans[0].get_text(strip=True)
            if len(spans) >= 2:
                code = spans[1].get_text(strip=True)
                
            if coach_div:
                name_raw = coach_div.get("etitle", "")
                name = re.sub(r'<[^>]*>', ' ', name_raw).strip()
                rake_class = " ".join(coach_div.get("class", []))
                
            rake_composition.append({
                "index": idx,
                "code": code,
                "name": name,
                "class": rake_class
            })
            
    # 3. Stops
    stops = []
    rows = soup.select("#sublowerdata table tr")
    for row in rows:
        stn_div = row.find("div", class_="fixwelps")
        if not stn_div:
            continue
            
        tds = row.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
            
        s_no_div = tds[0].find("div")
        s_no = s_no_div.get_text(strip=True) if s_no_div else ""
        
        code_small = tds[0].find("small")
        code = code_small.get_text(strip=True) if code_small else ""
        
        stn_name = stn_div.get_text(strip=True)
        
        dist_div = tds[2].find("div", class_="fixw70")
        distance = dist_div.get_text(strip=True) if dist_div else ""
        
        plat_small = tds[2].find("small")
        platform = ""
        if plat_small:
            plat_text = plat_small.get_text(" ", strip=True)
            plat_match = re.search(r'Platform:\s*(\d+)', plat_text, re.IGNORECASE)
            if plat_match:
                platform = plat_match.group(1)
                
        timing_divs = tds[4].find_all("div")
        arrival = timing_divs[0].get_text(strip=True) if len(timing_divs) > 0 else ""
        departure = timing_divs[1].get_text(strip=True) if len(timing_divs) > 1 else ""
        
        stops.append({
            "stop_number": s_no,
            "station_code": code,
            "station_name": stn_name,
            "distance": distance,
            "platform": platform,
            "arrival_time": arrival,
            "departure_time": departure
        })
        
    return {
        "train_name": train_name,
        "train_number": train_number,
        "route": route,
        "running_days": running_days,
        "classes": classes,
        "type": train_type,
        "zone": zone,
        "arp": arp,
        "rake_composition": rake_composition,
        "stops": stops
    }


def fetch_train_schedule_detailed(train_number: str) -> dict:
    train_number = train_number.strip()
    cache_key = f"detailed-{train_number}"
    
    # Check cache
    cached_data = get_schedule_cache(cache_key)
    if cached_data is not None:
        return cached_data
        
    html_content = None
    
    # Check for local mock files if codes match our local blueprints
    if train_number == "22603":
        mock_path = get_mock_file("schedule of train.txt")
        if mock_path:
            with open(mock_path, "r", encoding="utf-8") as f:
                content = f.read()
                html_start = content.find("<!DOCTYPE")
                html_content = content[html_start:] if html_start != -1 else content
                
    # Scrape if not loaded from mock
    if not html_content:
        url = f"https://etrain.info/train/{train_number}/schedule"
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                html_content = response.text
            else:
                return {"error": f"Error fetching train schedule: HTTP {response.status_code}"}
        except Exception as e:
            # Fallback to local files if request fails
            if train_number == "22603":
                mock_path = get_mock_file("schedule of train.txt")
                if mock_path:
                    with open(mock_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        html_start = content.find("<!DOCTYPE")
                        html_content = content[html_start:] if html_start != -1 else content
            if not html_content:
                return {"error": f"Error fetching train schedule from etrain.info: {str(e)}"}
                
    # Parse HTML
    result = parse_train_schedule_detailed(html_content)
    
    # Cache and return
    if result and result.get("stops") and "error" not in result:
        set_schedule_cache(cache_key, result)
        
    return result


def parse_fare_csv(csv_str):
    parts = csv_str.split(";")
    if len(parts) < 3:
        return None
        
    meta_parts = parts[0].split(",")
    distance = int(meta_parts[4]) if len(meta_parts) > 4 and meta_parts[4].isdigit() else 0
    
    classes_raw = parts[2].split("|")
    fares = {}
    for cls_raw in classes_raw:
        if ":" not in cls_raw:
            continue
        cls_name, weights_raw = cls_raw.split(":", 1)
        weights = weights_raw.split("~")
        if len(weights) >= 8:
            fares[cls_name] = {
                "ad0": int(weights[0]),
                "ad1": int(weights[1]),
                "ch0": int(weights[2]),
                "ch1": int(weights[3]),
                "srm0": int(weights[4]),
                "srm1": int(weights[5]),
                "srf0": int(weights[6]),
                "srf1": int(weights[7])
            }
    return {
        "distance": distance,
        "fares": fares
    }


def fetch_train_fare(train_number: str, src: str, dest: str) -> dict:
    train_number = train_number.strip()
    src = src.upper().strip()
    dest = dest.upper().strip()
    cache_key = f"fare-{train_number}-{src}-{dest}"
    
    # Check cache
    cached_data = get_route_cache(cache_key)
    if cached_data is not None:
        return cached_data
        
    url = "https://etrain.info/ajax.php?q=farecsv&v=3.4.11.0"
    
    try:
        data = {
            "ftrain": train_number,
            "src": src,
            "dest": dest,
            "reqID": "1",
            "reqCount": "1"
        }
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Referer": f"https://etrain.info/train/{train_number}/schedule",
            "Origin": "https://etrain.info",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest"
        }
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            json_res = response.json()
            csv_data = json_res.get("data", "")
            if csv_data:
                parsed = parse_fare_csv(csv_data)
                if parsed:
                    set_route_cache(cache_key, parsed)
                    return parsed
    except Exception as e:
        pass
        
    # Offline or Error Fallback:
    # Estimate fare based on distance or route template.
    # Total distance KGP to VM is 1830. Default fares defined above.
    schedule = fetch_train_schedule_detailed(train_number)
    if "error" not in schedule and "stops" in schedule:
        stops = schedule["stops"]
        src_stop = next((s for s in stops if s["station_code"] == src), None)
        dest_stop = next((s for s in stops if s["station_code"] == dest), None)
        
        if src_stop and dest_stop:
            try:
                d1 = int(re.sub(r'\D', '', src_stop["distance"]))
                d2 = int(re.sub(r'\D', '', dest_stop["distance"]))
                query_dist = abs(d2 - d1)
            except Exception:
                query_dist = 600
        else:
            query_dist = 600
    else:
        query_dist = 600
        
    defaults = {
        "2A": [2805, 3330, 1400, 1925, 1725, 3330, 1455, 3330],
        "3A": [1945, 2365, 975, 1395, 1205, 2365, 1020, 2365],
        "SL": [745, 945, 380, 580, 470, 945, 400, 945],
        "GN": [440, 440, 230, 230, 270, 440, 230, 440]
    }
    
    scaled_fares = {}
    ratio = query_dist / 1830.0
    for cls_name, weights in defaults.items():
        scaled_fares[cls_name] = {
            "ad0": int(max(10, round(weights[0] * ratio))),
            "ad1": int(max(10, round(weights[1] * ratio))),
            "ch0": int(max(10, round(weights[2] * ratio))),
            "ch1": int(max(10, round(weights[3] * ratio))),
            "srm0": int(max(10, round(weights[4] * ratio))),
            "srm1": int(max(10, round(weights[5] * ratio))),
            "srf0": int(max(10, round(weights[6] * ratio))),
            "srf1": int(max(10, round(weights[7] * ratio)))
        }
        
    result = {
        "distance": query_dist,
        "fares": scaled_fares,
        "is_fallback": True
    }
    set_route_cache(cache_key, result)
    return result


