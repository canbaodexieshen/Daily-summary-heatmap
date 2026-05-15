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


def safe_get_nested(data, *keys, default=None):
    """Safely get nested dictionary values. Returns default if any key is missing or value is None."""
    result = data
    for key in keys:
        if result is None:
            return default
        if not isinstance(result, dict):
            return default
        result = result.get(key)
    return result if result is not None else default


def parse_date_from_text(text):
    """
    从文本中提取日期，支持多种格式：
    - 2024-01-15
    - 2026年5月10日
    - 5月10日（自动补当年）
    - 2026/01/15
    """
    if not text:
        return None
    
    # 格式1: 2024-01-15
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    
    # 格式2: 2026/01/15
    match = re.search(r"(\d{4}/\d{2}/\d{2})", text)
    if match:
        return match.group(1).replace("/", "-")
    
    # 格式3: 2026年5月10日
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        y, m, d = match.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"
    
    # 格式4: 5月10日（当年）
    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        m, d = match.groups()
        current_y = datetime.datetime.now().year
        return f"{current_y}-{int(m):02d}-{int(d):02d}"
    
    return None


def extract_date_from_property(prop):
    """
    从 Notion 属性中提取日期值
    prop: Notion API 返回的属性对象
    returns: (date_str, created_time_str) 或 (None, None)
    """
    if prop is None:
        return None, None
    
    # 确保是字典
    if not isinstance(prop, dict):
        return None, None
    
    prop_type = prop.get("type")
    if not prop_type:
        return None, None
    
    date_val = None
    
    if prop_type == "date":
        date_obj = prop.get("date")
        if date_obj and isinstance(date_obj, dict):
            date_val = date_obj.get("start")
    
    elif prop_type == "created_time":
        date_val = prop.get("created_time")
    
    elif prop_type == "title":
        title_arr = prop.get("title")
        if title_arr and isinstance(title_arr, list) and len(title_arr) > 0:
            first_item = title_arr[0]
            if isinstance(first_item, dict):
                title_text = first_item.get("plain_text", "")
                date_val = parse_date_from_text(title_text)
    
    elif prop_type == "formula":
        formula_obj = prop.get("formula")
        if formula_obj and isinstance(formula_obj, dict):
            # formula 可能返回 string 或 date
            date_val = formula_obj.get("string") or safe_get_nested(formula_obj, "date", "start")
    
    elif prop_type == "rich_text":
        rt_arr = prop.get("rich_text")
        if rt_arr and isinstance(rt_arr, list) and len(rt_arr) > 0:
            first_item = rt_arr[0]
            if isinstance(first_item, dict):
                rt_text = first_item.get("plain_text", "")
                date_val = parse_date_from_text(rt_text)
    
    # 标准化日期格式
    if date_val:
        date_str = str(date_val).split("T")[0]
        return date_str, date_val
    
    return None, None


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
    skipped_count = 0

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
                results = res.get("results", [])
                
                if total_fetched == 0:
                    print(f"[INFO] Total pages in database: {len(results)}")
                
                for idx, result in enumerate(results):
                    total_fetched += 1
                    
                    # 防御性检查：确保 result 是字典
                    if not isinstance(result, dict):
                        skipped_count += 1
                        continue
                    
                    # 获取 properties
                    props = result.get("properties")
                    if props is None or not isinstance(props, dict):
                        skipped_count += 1
                        continue
                    
                    # 调试：打印第一个页面的属性结构
                    if total_fetched == 1:
                        print(f"[DEBUG] First page has {len(props)} properties:")
                        all_prop_names = list(props.keys())
                        print(f"  All property names: {all_prop_names}")
                        
                        # 查找"日期"属性
                        date_prop_name = None
                        for name in all_prop_names:
                            if "日期" in name or "日期" in name:
                                date_prop_name = name
                                break
                        
                        if date_prop_name:
                            print(f"  [FOUND] Date property: '{date_prop_name}'")
                            date_prop = props.get(date_prop_name)
                            print(f"  [DEBUG] Date property value: {json.dumps(date_prop, ensure_ascii=False)[:300]}")
                    
                    # 查找日期属性（尝试不同的名称）
                    date_prop = None
                    date_prop_name = None
                    
                    # 首先尝试精确匹配
                    if "日期" in props:
                        date_prop_name = "日期"
                        date_prop = props.get("日期")
                    else:
                        # 尝试模糊匹配
                        for name in props.keys():
                            if "日期" in name or name == "Name" or name == "名称":
                                date_prop_name = name
                                date_prop = props.get(name)
                                break
                    
                    # 提取日期
                    date_str = None
                    if date_prop:
                        date_str, _ = extract_date_from_property(date_prop)
                    
                    # 如果仍未找到日期，尝试从页面标题提取
                    if not date_str:
                        title_prop = props.get("Name") or props.get("名称") or props.get("title")
                        if title_prop:
                            date_str, _ = extract_date_from_property(title_prop)
                    
                    # 获取创建时间（优先使用页面的 created_time）
                    created_time = result.get("created_time")
                    
                    if date_str:
                        # 保留当天最早的创建时间
                        if date_str not in data_dict or (created_time and data_dict.get(date_str) is None):
                            data_dict[date_str] = created_time
                        elif created_time and created_time < data_dict.get(date_str, created_time):
                            data_dict[date_str] = created_time
                    else:
                        skipped_count += 1

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
            import traceback
            traceback.print_exc()
            sys.exit(1)

    print(f"Fetched {len(data_dict)} days of daily summary records (total {total_fetched} pages, skipped {skipped_count} invalid)")
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
    # 匹配 "2026: 0 次" 或 "2026: 0 分钟" 格式
    content = re.sub(
        rf"({current_year}:\s*)[0-9\.]+(\s*(?:分钟|次))",
        rf"\g<1>{total_count} 次",
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
    # 从环境变量读取凭证
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
    
    # 5. 同时保存到根目录，方便 GitHub Pages 直接访问
    root_dest = "main.svg"
    import shutil
    shutil.copy2(dest, root_dest)
    print(f"[OK] Also copied to {root_dest} for GitHub Pages")


if __name__ == "__main__":
    main()
