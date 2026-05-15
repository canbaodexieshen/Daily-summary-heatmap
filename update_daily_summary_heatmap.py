import os
import subprocess
import datetime
import re
import sys
import urllib.request
import urllib.error
import json


def validate_database_id(database_id):
    """Validate database ID format"""
    clean_id = database_id.replace("-", "")
    if len(clean_id) != 32:
        return False, f"Database ID length is incorrect: {len(clean_id)} characters (should be 32)"
    return True, ""


def verify_notion_connection(token, db_id):
    """Verify Notion connection"""
    print("Verifying Notion connection...")
    url = f"https://api.notion.com/v1/databases/{db_id}"
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }

    req = urllib.request.Request(url, headers=auth_headers, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read())
            if "title" in res:
                title = res["title"][0]["plain_text"] if res["title"] else "No title"
                print(f"[OK] Database connected: {title}")
                return True, res
            else:
                return False, "Invalid database response format"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        if e.code == 401:
            return False, "Authentication failed - please check NOTION_TOKEN"
        elif e.code == 404:
            return False, "Database not found - please check NOTION_DATABASE_ID and ensure Integration is connected"
        else:
            return False, f"HTTP error {e.code}: {error_body[:200]}"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"


def get_notion_data(token, database_id):
    """从 Notion 每日总结数据库拉取所有页面，提取日期和创建时间"""
    print("Fetching daily summary data from Notion...")
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    data_dict = {}  # {date_str: creation_time_str}
    has_more = True
    next_cursor = None
    total_fetched = 0

    while has_more:
        body = {}
        if next_cursor:
            body["start_cursor"] = next_cursor
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read())
                for result in res.get("results", []):
                    total_fetched += 1
                    props = result.get("properties", {})

                    # 读取"日期"属性（兼容 date / created_time 等类型）
                    date_val = None
                    date_prop = props.get("日期")
                    if date_prop:
                        ptype = date_prop.get("type")
                        if ptype == "date":
                            date_val = date_prop.get("date", {}).get("start")
                        elif ptype == "created_time":
                            ct = date_prop.get("created_time")
                            if ct:
                                date_val = ct.split("T")[0]

                    # 读取"创建时间"属性
                    # 优先使用页面自带的 created_time
                    created_time = result.get("created_time")

                    # 如果有自定义的"创建时间"属性，优先使用它
                    ct_prop = props.get("创建时间")
                    if ct_prop:
                        ptype = ct_prop.get("type")
                        if ptype == "created_time":
                            created_time = ct_prop.get("created_time")
                        elif ptype == "date":
                            created_time = ct_prop.get("date", {}).get("start")

                    if date_val:
                        date_str = str(date_val).split("T")[0]
                        # 保留当天最早的创建时间
                        if date_str not in data_dict or (created_time and created_time < data_dict[date_str]):
                            data_dict[date_str] = created_time

                has_more = res.get("has_more", False)
                next_cursor = res.get("next_cursor")

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            if e.code == 404:
                print("[ERROR] Database not found")
                print("   Possible reasons:")
                print("   1. NOTION_DATABASE_ID is incorrect")
                print("   2. Notion Integration is not connected to this database")
                print("   3. Database was deleted or permissions changed")
                print(f"   Database ID: {database_id}")
                sys.exit(1)
            elif e.code == 401:
                print("[ERROR] Authentication failed")
                print("   Please check if NOTION_TOKEN is correct")
                sys.exit(1)
            elif e.code == 403:
                print("[ERROR] Permission denied")
                print("   Make sure the Notion Integration is connected and has read access")
                sys.exit(1)
            else:
                print(f"[ERROR] HTTP {e.code}: {error_body[:500]}")
                sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Failed to get Notion data: {e}")
            sys.exit(1)

    print(f"Fetched {len(data_dict)} days of daily summary records (total {total_fetched} pages)")
    return data_dict


def calculate_intensity(created_time_str):
    """
    Calculate color intensity based on creation time (0.0 ~ 1.0)
    Rule: closer to midnight (23:59:59) = darker color
    """
    if not created_time_str:
        return 0.0

    try:
        dt = datetime.datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        else:
            dt = dt + datetime.timedelta(hours=8)

        hour = dt.hour
        minute = dt.minute
        second = dt.second

        total_seconds = hour * 3600 + minute * 60 + second
        max_seconds = 23 * 3600 + 59 * 60 + 59

        intensity = total_seconds / max_seconds
        return min(1.0, max(0.0, intensity))
    except Exception as e:
        print(f"[WARN] Failed to parse time: {created_time_str}, {e}")
        return 0.0


def interpolate_color(color1, color2, factor):
    """根据 factor (0.0~1.0) 在两个十六进制颜色之间线性插值"""
    factor = max(0.0, min(1.0, factor))
    c1 = [int(color1[i : i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(color2[i : i + 2], 16) for i in (1, 3, 5)]
    res = [int(c1[i] + (c2[i] - c1[i]) * factor) for i in range(3)]
    return f"#{res[0]:02x}{res[1]:02x}{res[2]:02x}"


def get_color_for_intensity(intensity):
    """
    根据强度（0.0~1.0）映射到绿色系颜色：
      0.0 (无记录) → #ebedf0 (GitHub 灰)
      0.0+ (刚过午夜) → #c6e48b (浅绿)
      0.5 (中午) → #7bc96f (中绿)
      1.0 (接近午夜) → #239a3b (深绿)
    """
    if intensity <= 0:
        return "#ebedf0"

    if intensity < 0.5:
        return interpolate_color("#c6e48b", "#7bc96f", intensity * 2)
    else:
        return interpolate_color("#7bc96f", "#239a3b", (intensity - 0.5) * 2)


def process_svg_styling(file_path, data_dict, current_year):
    """Apply gradient colors to SVG and update statistics"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update statistics text
    total_count = len(data_dict)
    content = re.sub(
        rf"({current_year}:\s*)[0-9\.]+(\s*分钟)",
        rf"\g<1>{total_count} days",
        content,
    )

    # 2. Apply gradient colors and update title for each date cell
    def rect_replacer(match):
        rect_tag = match.group(0)
        date_match = re.search(r"<title>(\d{4}-\d{2}-\d{2})</title>", rect_tag)
        if not date_match:
            return rect_tag

        date_str = date_match.group(1)
        created_time = data_dict.get(date_str)
        intensity = calculate_intensity(created_time)
        color = get_color_for_intensity(intensity)

        # Update <title> tag
        if created_time:
            try:
                dt = datetime.datetime.fromisoformat(created_time.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
                else:
                    dt = dt + datetime.timedelta(hours=8)
                time_str = dt.strftime("%H:%M")
            except:
                time_str = "unknown"
            title_text = f"{date_str} - {time_str}"
        else:
            title_text = f"{date_str} - no record"

        rect_tag = re.sub(
            r"<title>\d{4}-\d{2}-\d{2}</title>",
            f"<title>{title_text}</title>",
            rect_tag,
            count=1
        )

        return re.sub(r'fill="[^"]+"', f'fill="{color}"', rect_tag, count=1)

    content = re.sub(
        r'<rect\b[^>]*><title>.*?</title></rect>',
        rect_replacer,
        content,
        flags=re.DOTALL,
    )

    # 3. Add white background
    if 'id="background"' not in content:
        content = content.replace("<svg ", '<svg style="background-color:white;" ', 1)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Styling complete: {total_count} days with daily summary")


def generate_heatmap(notion_token, database_id, year):
    """Generate base SVG using github_heatmap CLI"""
    command = [
        "github_heatmap",
        "notion",
        "--notion_token", notion_token,
        "--database_id", database_id,
        "--date_prop_name", "日期",
        "--value_prop_name", "总时长",
        "--unit", "次",
        "--year", str(year),
        "--me", "Daily Summary Heatmap",
        "--without-type-name",
        "--background-color", "#FFFFFF",
        "--track-color", "#ebedf0",
        "--dom-color", "#ebedf0",
        "--text-color", "#000000",
    ]

    print(f"Generating {year} heatmap template...")
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(f"Warning: {result.stderr}")

    return "OUT_FOLDER/notion.svg"


def main():
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not notion_token or not database_id:
        print("[ERROR] Missing required environment variables")
        if not notion_token:
            print("   - NOTION_TOKEN not set")
        if not database_id:
            print("   - NOTION_DATABASE_ID not set")
        print("")
        print("Please set the following secrets in GitHub repository Settings > Secrets:")
        print("   - NOTION_TOKEN: Your Notion Integration Token")
        print("   - NOTION_DATABASE_ID: Database ID for daily summary")
        sys.exit(1)

    # 验证数据库 ID 格式
    valid, msg = validate_database_id(database_id)
    if not valid:
        print(f"[WARN] {msg}")
        print("   Continuing anyway...")

    print(f"Using database ID: {database_id[:8]}...{database_id[-4:]}")

    # 验证 Notion 连接
    connected, result = verify_notion_connection(notion_token, database_id)
    if not connected:
        print(f"[ERROR] Connection failed: {result}")
        sys.exit(1)

    current_year = datetime.datetime.now().year
    year_str = os.getenv("YEAR", "")
    target_year = int(year_str) if year_str and year_str.strip() else current_year

    # 1. Fetch Notion data
    real_data = get_notion_data(notion_token, database_id)

    # 2. Generate base SVG
    svg_path = generate_heatmap(notion_token, database_id, target_year)

    if not os.path.exists(svg_path):
        print(f"[ERROR] SVG template not generated: {svg_path}")
        sys.exit(1)

    # 3. Apply styling
    print("Applying gradient colors...")
    process_svg_styling(svg_path, real_data, target_year)

    # 4. Move to output directory
    os.makedirs("daily_summary_heatmap", exist_ok=True)
    dest = "daily_summary_heatmap/main.svg"
    os.replace(svg_path, dest)
    print(f"[OK] Heatmap saved to {dest}")


if __name__ == "__main__":
    main()
