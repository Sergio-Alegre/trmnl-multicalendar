from dotenv import load_dotenv
import datetime
import hashlib
import icalendar
import json
import locale
import os
import pytz
import recurring_ical_events
import requests

load_dotenv()

DEBUG = os.getenv('DEBUG', default=False)
trmnl_ics_urls = os.getenv('TRMNL_ICS_URL', default='').split(',')
trmnl_tz = os.getenv('TRMNL_TZ')
trmnl_locale = os.getenv('TRMNL_LOCALE')

if trmnl_locale:
    locale.setlocale(locale.LC_ALL, trmnl_locale)

local_tz = pytz.timezone(trmnl_tz)
now = datetime.datetime.now(local_tz)

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.push_state.json')


def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


merged_calendar = icalendar.Calendar()
for ics_url in trmnl_ics_urls:
    ics_url = ics_url.strip()
    if not ics_url:
        continue
    response = requests.get(ics_url)
    response.raise_for_status()
    cal = icalendar.Calendar.from_ical(response.text)
    for name, value in cal.property_items(recursive=False):
        if name not in merged_calendar:
            merged_calendar.add(name, value)
    for component in cal.walk('VEVENT'):
        merged_calendar.add_component(component)

query = recurring_ical_events.of(merged_calendar)

STYLE_RESET = '<style>* { margin:0; padding:0; box-sizing:border-box; -webkit-font-smoothing:none; text-rendering:optimizeSpeed; }</style>'


def to_local(value):
    # Los datetimes con zona (p. ej. eventos en UTC) se pasan a trmnl_tz; las fechas
    # de día completo y los datetimes sin zona (hora flotante) se dejan tal cual.
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.astimezone(local_tz)
    return value


def is_all_day(event):
    start = event["DTSTART"].dt
    return isinstance(start, datetime.date) and not isinstance(start, datetime.datetime)


def event_start(event):
    return to_local(event["DTSTART"].dt)


def event_end(event):
    return to_local(event["DTEND"].dt) if "DTEND" in event else None


def events_on(date):
    # query.at(date) interpreta el día en UTC, así que un evento a las 00:30 locales
    # caería en el día anterior. Los eventos con hora se consultan por el rango del día
    # en trmnl_tz; los de día completo no dependen de la zona y se consultan por fecha
    # (con rango con zona, el día del cambio de hora arrastraría el del día siguiente).
    day_start = local_tz.localize(datetime.datetime.combine(date, datetime.time.min))
    day_end = local_tz.localize(datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time.min))
    all_day_events = [event for event in query.at(date) if is_all_day(event)]
    timed_events = [event for event in query.between(day_start, day_end) if not is_all_day(event)]
    return all_day_events + timed_events


def event_sort_key(event):
    # Clave estable para ordenar eventos entre ejecuciones distintas del script,
    # ya que query.between() no garantiza el mismo orden en cada proceso.
    end = event_end(event)
    start_key = event_start(event).isoformat()
    end_key = end.isoformat() if end is not None else ""
    summary = str(event.get("SUMMARY", ""))
    uid = str(event.get("UID", ""))
    return (start_key, end_key, summary, uid)


def build_week_view(week_offset):
    start_date = now.date() - datetime.timedelta(days=now.weekday()) + datetime.timedelta(weeks=week_offset)
    trmnl_days = 7
    updated_at = now.strftime("%d.%m %H:%M")

    HOUR_START = 8
    HOUR_END = 24
    HOURS = HOUR_END - HOUR_START
    TOTAL_HEIGHT = 480
    HEADER_HEIGHT = 21
    ALLDAY_ROW_HEIGHT = 15
    OFFHOUR_ROW_HEIGHT = 24
    HOUR_LABEL_WIDTH = 24
    MARKER_HOURS = [8, 12, 16, 20]

    def clamp_hour(dt):
        h = dt.hour + dt.minute / 60
        return max(HOUR_START, min(HOUR_END, h))

    dates = [start_date + datetime.timedelta(days=i) for i in range(trmnl_days)]

    days_data = []
    day_heights = []
    fingerprint_parts = []
    for date in dates:
        events = events_on(date)
        all_day_events = []
        timed_events = []
        for event in events:
            if is_all_day(event):
                all_day_events.append(event)
            else:
                timed_events.append(event)

        allday_badges = [str(event.get("SUMMARY", "")) for event in all_day_events]
        offhour_badges = []
        grid_events = []
        for event in timed_events:
            start, end = event_start(event), event_end(event)
            raw_start = start.hour + start.minute / 60
            raw_end = (end.hour + end.minute / 60) if end is not None else raw_start + 1
            if raw_end <= HOUR_START or raw_start >= HOUR_END:
                summary = str(event.get("SUMMARY", "Sin título"))
                start_label = start.strftime("%H:%M")
                end_label = end.strftime("%H:%M") if end is not None else ""
                time_range = f"{start_label}-{end_label}" if end_label else start_label
                offhour_badges.append((summary, time_range))
            else:
                grid_events.append(event)

        day_heights.append(len(allday_badges) * ALLDAY_ROW_HEIGHT + len(offhour_badges) * OFFHOUR_ROW_HEIGHT)
        days_data.append({"date": date, "allday_badges": allday_badges, "offhour_badges": offhour_badges, "timed_events": grid_events})

        fingerprint_parts.append(date.isoformat())
        fingerprint_parts.extend(sorted(allday_badges))
        fingerprint_parts.extend(sorted(f"{summary}|{time_range}" for summary, time_range in offhour_badges))
        for event in sorted(grid_events, key=event_sort_key):
            end = event_end(event)
            start_key = event_start(event).isoformat()
            end_key = end.isoformat() if end is not None else ""
            summary = str(event.get("SUMMARY", ""))
            fingerprint_parts.append(f"{start_key}|{end_key}|{summary}")

    fingerprint = hashlib.sha256("\n".join(fingerprint_parts).encode("utf-8")).hexdigest()

    ALLDAY_HEIGHT = max(max(day_heights, default=0), ALLDAY_ROW_HEIGHT)
    GRID_HEIGHT = TOTAL_HEIGHT - HEADER_HEIGHT - ALLDAY_HEIGHT
    HOUR_HEIGHT = GRID_HEIGHT / HOURS

    marker_lines_html = ""
    for mh in MARKER_HOURS:
        top = (mh - HOUR_START) * HOUR_HEIGHT
        marker_lines_html += f'<div style="position:absolute; top:{top}px; left:0; right:0; height:1px; background-image:repeating-linear-gradient(to right, #000 0, #000 2px, transparent 2px, transparent 4px);"></div>'

    label_column_html = f'<div style="height:{HEADER_HEIGHT + ALLDAY_HEIGHT}px; display:flex; align-items:center; justify-content:center; text-align:center; font-size:7px; font-weight:bold; line-height:1.3; color:#000;">{updated_at.replace(" ", "<br>")}</div><div style="position:relative; height:{GRID_HEIGHT}px;">{marker_lines_html}'
    for h in range(HOUR_START, HOUR_END):
        top = (h - HOUR_START) * HOUR_HEIGHT
        label = f"{h % 24}h"
        label_column_html += f'<div style="position:absolute; top:{top + 1}px; right:3px; font-size:12px; font-weight:bold; line-height:1; white-space:nowrap; color:#000;">{label}</div>'
    label_column_html += '</div>'

    day_columns_html = ""
    for i, day in enumerate(days_data):
        date = day["date"]
        is_friday = date.weekday() == 4
        allday_badges = day["allday_badges"]
        offhour_badges = day["offhour_badges"]
        timed_events = day["timed_events"]

        allday_html = "".join(
            f'<div style="background:#000; color:#fff; font-size:10px; line-height:10px; padding:1px 3px; margin-bottom:1px; border-radius:2px; box-sizing:border-box;">{badge}</div>'
            for badge in allday_badges
        )
        allday_html += "".join(
            f'<div style="background:#eee; border:1px solid #000; border-radius:2px; padding:1px 3px; margin-bottom:1px; box-sizing:border-box; font-size:9px; line-height:1.15; overflow:hidden;"><strong>{summary}</strong><br>{time_range}</div>'
            for summary, time_range in offhour_badges
        )

        timed_events_info = []
        for event in timed_events:
            end = event_end(event)
            start_h = clamp_hour(event_start(event))
            end_h = clamp_hour(end) if end is not None else min(start_h + 1, HOUR_END)
            if end_h <= start_h:
                end_h = min(start_h + 0.5, HOUR_END)
            timed_events_info.append({"event": event, "start_h": start_h, "end_h": end_h})

        timed_events_info.sort(key=lambda x: (x["start_h"], x["end_h"]))

        clusters = []
        current_cluster = []
        cluster_end = None
        for info in timed_events_info:
            if current_cluster and info["start_h"] < cluster_end:
                current_cluster.append(info)
                cluster_end = max(cluster_end, info["end_h"])
            else:
                if current_cluster:
                    clusters.append(current_cluster)
                current_cluster = [info]
                cluster_end = info["end_h"]
        if current_cluster:
            clusters.append(current_cluster)

        for cluster in clusters:
            columns_end = []
            for info in cluster:
                placed = False
                for col_idx in range(len(columns_end)):
                    if info["start_h"] >= columns_end[col_idx]:
                        columns_end[col_idx] = info["end_h"]
                        info["col"] = col_idx
                        placed = True
                        break
                if not placed:
                    columns_end.append(info["end_h"])
                    info["col"] = len(columns_end) - 1
            total_cols = len(columns_end)
            for info in cluster:
                info["total_cols"] = total_cols

        events_html = ""
        for info in timed_events_info:
            event = info["event"]
            start_h = info["start_h"]
            end_h = info["end_h"]
            col = info["col"]
            total_cols = info["total_cols"]
            top = (start_h - HOUR_START) * HOUR_HEIGHT
            height = max((end_h - start_h) * HOUR_HEIGHT, 16)
            col_width_pct = 100 / total_cols
            left_pct = col * col_width_pct
            end = event_end(event)
            start_label = event_start(event).strftime("%H:%M")
            end_label = end.strftime("%H:%M") if end is not None else ""
            summary = str(event.get("SUMMARY", "Sin título"))
            events_html += f'''
            <div style="position:absolute; top:{top}px; height:{height}px; left:calc({left_pct}% + 1px); width:calc({col_width_pct}% - 2px);
                        background:#eee; border:1px solid #000; border-radius:2px; padding:1px 3px;
                        font-size:10px; line-height:1.2; overflow:hidden; box-sizing:border-box;">
              <strong>{summary}</strong><br>{start_label}-{end_label}
            </div>'''

        day_label = date.strftime("%d.%m")
        border_right = "border-right: 2px solid #000;" if is_friday else ("border-right: 1px solid #000;" if i < trmnl_days - 1 else "")

        day_columns_html += f'''
        <div style="flex: 1 1 0; min-width: 0; {border_right}">
          <div style="height:{HEADER_HEIGHT}px; display:flex; align-items:flex-start; justify-content:center; font-size:18px; font-weight:bold; line-height:1; padding-top:1px;">{day_label}</div>
          <div style="height:{ALLDAY_HEIGHT}px; padding:0 3px; overflow:hidden;">{allday_html}</div>
          <div style="position:relative; height:{GRID_HEIGHT}px; background-image: repeating-linear-gradient(white 0, white {HOUR_HEIGHT - 1}px, #ddd {HOUR_HEIGHT - 1}px, #ddd {HOUR_HEIGHT}px); margin:0 1px;">
            {marker_lines_html}
            {events_html}
          </div>
        </div>'''

    markup = f'''
    {STYLE_RESET}
    <div style="width:800px; height:480px; display:flex; margin:0; padding:0; background:#fff;">
      <div style="width:{HOUR_LABEL_WIDTH}px; flex-shrink:0;">{label_column_html}</div>
      {day_columns_html}
    </div>
    '''
    return markup, fingerprint


def build_month_view(month_offset):
    total = now.year * 12 + (now.month - 1) + month_offset
    target_year, target_month = divmod(total, 12)
    target_month += 1

    first_of_month = datetime.date(target_year, target_month, 1)
    grid_start = first_of_month - datetime.timedelta(days=first_of_month.weekday())
    if target_month == 12:
        first_of_next_month = datetime.date(target_year + 1, 1, 1)
    else:
        first_of_next_month = datetime.date(target_year, target_month + 1, 1)
    last_of_month = first_of_next_month - datetime.timedelta(days=1)
    grid_end = last_of_month + datetime.timedelta(days=(6 - last_of_month.weekday()))

    weeks = []
    cursor = grid_start
    while cursor <= grid_end:
        weeks.append([cursor + datetime.timedelta(days=i) for i in range(7)])
        cursor += datetime.timedelta(days=7)

    num_weeks = len(weeks)

    TOTAL_HEIGHT = 480
    TOTAL_WIDTH = 800
    WEEKDAY_HEADER_HEIGHT = 16
    WEEK_ROW_HEIGHT = (TOTAL_HEIGHT - WEEKDAY_HEADER_HEIGHT) / num_weeks

    header_html = f'<div style="display:flex; height:{WEEKDAY_HEADER_HEIGHT}px;">'
    for i, date in enumerate(weeks[0]):
        border_right = "border-right: 2px solid #000;" if i == 4 else ("border-right: 1px solid #000;" if i < 6 else "")
        label = date.strftime("%a").upper()
        header_html += f'<div style="flex:1 1 0; min-width:0; {border_right} display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:bold; color:#000;">{label}</div>'
    header_html += '</div>'

    fingerprint_parts = []
    rows_html = ""
    for w_idx, week in enumerate(weeks):
        border_bottom = "border-bottom: 1px solid #000;" if w_idx < num_weeks - 1 else ""
        rows_html += f'<div style="display:flex; height:{WEEK_ROW_HEIGHT}px; {border_bottom}">'
        for i, date in enumerate(week):
            is_friday = i == 4
            border_right = "border-right: 2px solid #000;" if is_friday else ("border-right: 1px solid #000;" if i < 6 else "")

            events = events_on(date)
            all_day_events = []
            timed_events = []
            for event in events:
                if is_all_day(event):
                    all_day_events.append(event)
                else:
                    timed_events.append(event)
            all_day_events.sort(key=event_sort_key)
            timed_events.sort(key=event_sort_key)

            fingerprint_parts.append(date.isoformat())
            for event in all_day_events:
                fingerprint_parts.append(f"A|{str(event.get('SUMMARY', ''))}")
            for event in timed_events:
                start = event_start(event).isoformat()
                summary = str(event.get("SUMMARY", ""))
                fingerprint_parts.append(f"T|{start}|{summary}")

            # %-d no existe en strftime de Windows, por eso se usa date.day
            day_label = f"{date.day} de {date.strftime('%b')}" if date.day == 1 else str(date.day)

            items_html = ""
            for event in all_day_events:
                summary = str(event.get("SUMMARY", ""))
                items_html += f'<div style="background:#000; color:#fff; font-size:12px; line-height:13px; padding:0 2px; margin-bottom:1px; border-radius:1px; box-sizing:border-box; overflow:hidden; white-space:nowrap;">{summary}</div>'
            for event in timed_events:
                summary = str(event.get("SUMMARY", "Sin título"))
                start_label = event_start(event).strftime("%H:%M")
                items_html += f'<div style="font-size:12px; line-height:13px; color:#000; overflow:hidden; white-space:nowrap; text-overflow:ellipsis;">&bull; {start_label} {summary}</div>'

            rows_html += f'''
            <div style="flex:1 1 0; min-width:0; {border_right} padding:1px 2px; overflow:hidden; box-sizing:border-box;">
              <div style="font-size:10px; font-weight:bold; color:#000; line-height:1.1; margin-bottom:1px;">{day_label}</div>
              {items_html}
            </div>'''
        rows_html += '</div>'

    fingerprint = hashlib.sha256("\n".join(fingerprint_parts).encode("utf-8")).hexdigest()

    markup = f'''
    {STYLE_RESET}
    <div style="width:{TOTAL_WIDTH}px; height:{TOTAL_HEIGHT}px; background:#fff; margin:0; padding:0;">
      {header_html}
      {rows_html}
    </div>
    '''
    return markup, fingerprint


targets = []
week_current_url = os.getenv('TRMNL_WEBHOOK_URL_WEEK_CURRENT')
if week_current_url:
    markup, fingerprint = build_week_view(0)
    targets.append(("semana actual", week_current_url, markup, fingerprint))
week_next_url = os.getenv('TRMNL_WEBHOOK_URL_WEEK_NEXT')
if week_next_url:
    markup, fingerprint = build_week_view(1)
    targets.append(("semana siguiente", week_next_url, markup, fingerprint))
month_url = os.getenv('TRMNL_WEBHOOK_URL_MONTH')
if month_url:
    markup, fingerprint = build_month_view(0)
    targets.append(("mes", month_url, markup, fingerprint))

if DEBUG and not targets:
    print("No hay ningún TRMNL_WEBHOOK_URL_* configurado en .env")

state = load_state()
state_changed = False

for name, url, markup, fingerprint in targets:
    if state.get(name) == fingerprint:
        if DEBUG:
            print(f"--- {name}: sin cambios, no se envía ---")
        continue

    if DEBUG:
        print(f"--- {name} ---")
        print(markup)

    r = requests.post(url, json={"merge_variables": {"calendar_html": markup}})

    if DEBUG:
        print(r.status_code)
        print(r.text)

    if r.ok:
        state[name] = fingerprint
        state_changed = True

if state_changed:
    save_state(state)
