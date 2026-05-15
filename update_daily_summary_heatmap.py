import os
import subprocess
import datetime
import re
import sys
import urllib.request
import json


def get_notion_data(token, database_id):
    """从 Notion 每日总结数据库拉取所有页面，提取日期和创建时间"""
    print("正在连接 Notion 数据库并抓取每日总结数据...")
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    data_dict = {}  # {date_str: creation_time_str}
    has_more = True
    next_cursor = None

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
                    props = result.get("properties", {})

                    # 读取"日期"属性
                    date_val = None
                    if props.get("日期") and props["日期"].get("date"):
                        date_val = props["日期"]["date"].get("start")

                    # 读取"创建时间"属性（created_time 或自定义属性）
                    # 优先使用 result 自带的 created_time
                    created_time = result.get("created_time")

                    # 如果有自定义的"创建时间"属性，优先使用它
                    if props.get("创建时间"):
                        ct_prop = props["创建时间"]
                        if ct_prop.get("type") == "created_time":
                            created_time = ct_prop.get("created_time")
                        elif ct_prop.get("type") == "date":
                            created_time = ct_prop.get("date", {}).get("start")

                    if date_val:
                        date_str = str(date_val).split("T")[0]
                        # 保留当天最早的创建时间
                        if date_str not in data_dict or (created_time and created_time < data_dict[date_str]):
                            data_dict[date_str] = created_time

                has_more = res.get("has_more", False)
                next_cursor = res.get("next_cursor")
        except Exception as e:
            print(f"获取 Notion 数据失败: {e}")
            sys.exit(1)

    print(f"共读取到 {len(data_dict)} 天的每日总结记录")
    return data_dict


def calculate_intensity(created_time_str):
    """
    根据创建时间计算颜色强度（0.0 ~ 1.0）
    规则：越靠近午夜 23:59:59，颜色越深
    """
    if not created_time_str:
        return 0.0

    try:
        # 解析创建时间
        dt = datetime.datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
        # 转换为当天本地时间（假设用户使用北京时间 UTC+8）
        # 如果时间带有时区信息，先转换
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        else:
            dt = dt + datetime.timedelta(hours=8)

        hour = dt.hour
        minute = dt.minute
        second = dt.second

        # 计算当天总秒数（从 00:00:00 开始）
        total_seconds = hour * 3600 + minute * 60 + second

        # 午夜 23:59:59 = 86399 秒
        # 越靠近午夜，数值越接近 1.0
        max_seconds = 23 * 3600 + 59 * 60 + 59  # 86399

        intensity = total_seconds / max_seconds
        return min(1.0, max(0.0, intensity))
    except Exception as e:
        print(f"解析时间出错: {created_time_str}, {e}")
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

    # 分段渐变：浅绿 → 中绿 → 深绿
    if intensity < 0.5:
        return interpolate_color("#c6e48b", "#7bc96f", intensity * 2)
    else:
        return interpolate_color("#7bc96f", "#239a3b", (intensity - 0.5) * 2)


def process_svg_styling(file_path, data_dict, current_year):
    """对底稿 SVG 执行渐变着色，并修正年度统计文字"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. 修正统计文字
    total_count = len(data_dict)
    content = re.sub(
        rf"({current_year}:\s*)[0-9\.]+(\s*分钟)",
        rf"\g<1>{total_count} 天",
        content,
    )

    # 2. 对每个日期格子应用渐变颜色，并更新 title
    def rect_replacer(match):
        rect_tag = match.group(0)
        date_match = re.search(r"<title>(\d{4}-\d{2}-\d{2})</title>", rect_tag)
        if not date_match:
            return rect_tag

        date_str = date_match.group(1)
        created_time = data_dict.get(date_str)
        intensity = calculate_intensity(created_time)
        color = get_color_for_intensity(intensity)

        # 更新 <title> 标签
        if created_time:
            # 格式化显示时间
            try:
                dt = datetime.datetime.fromisoformat(created_time.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
                else:
                    dt = dt + datetime.timedelta(hours=8)
                time_str = dt.strftime("%H:%M")
            except:
                time_str = "未知"
            title_text = f"{date_str} - {time_str}"
        else:
            title_text = f"{date_str} - 无记录"

        rect_tag = re.sub(
            r"<title>\d{4}-\d{2}-\d{2}</title>",
            f"<title>{title_text}</title>",
            rect_tag,
            count=1
        )

        # 只替换第一个 fill 属性
        return re.sub(r'fill="[^"]+"', f'fill="{color}"', rect_tag, count=1)

    content = re.sub(
        r'<rect\b[^>]*><title>.*?</title></rect>',
        rect_replacer,
        content,
        flags=re.DOTALL,
    )

    # 3. 补充白色背景
    if 'id="background"' not in content:
        content = content.replace("<svg ", '<svg style="background-color:white;" ', 1)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"着色完成：共 {total_count} 天有每日总结")


def generate_heatmap(notion_token, database_id, year):
    """调用 github_heatmap CLI 生成底稿 SVG"""
    command = [
        "github_heatmap",
        "notion",
        "--notion_token", notion_token,
        "--database_id", database_id,
        "--date_prop_name", "日期",
        "--value_prop_name", "总时长",
        "--unit", "次",
        "--year", str(year),
        "--me", "每日总结热力图",
        "--without-type-name",
        "--background-color", "#FFFFFF",
        "--track-color", "#ebedf0",
        "--dom-color", "#ebedf0",
        "--text-color", "#000000",
    ]

    print(f"正在调用热力图引擎生成 {year} 年底稿...")
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)

    return "OUT_FOLDER/notion.svg"


def main():
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")

    if not notion_token or not database_id:
        print("缺少必要的环境变量：NOTION_TOKEN 或 NOTION_DATABASE_ID")
        sys.exit(1)

    current_year = datetime.datetime.now().year
    year_str = os.getenv("YEAR", "")
    target_year = int(year_str) if year_str and year_str.strip() else current_year

    # 1. 拉取 Notion 数据
    real_data = get_notion_data(notion_token, database_id)

    # 2. 生成底稿 SVG
    svg_path = generate_heatmap(notion_token, database_id, target_year)

    if not os.path.exists(svg_path):
        print(f"底稿 SVG 未生成: {svg_path}")
        sys.exit(1)

    # 3. 渐变着色 + 统计注入
    print("正在执行渐变着色...")
    process_svg_styling(svg_path, real_data, target_year)

    # 4. 移动到 daily_summary_heatmap/main.svg
    os.makedirs("daily_summary_heatmap", exist_ok=True)
    dest = "daily_summary_heatmap/main.svg"
    os.replace(svg_path, dest)
    print(f"热力图已保存至 {dest}")


if __name__ == "__main__":
    main()
