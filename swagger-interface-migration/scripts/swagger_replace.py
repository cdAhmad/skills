#!/usr/bin/env python3
import json
import os
import re
import argparse
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

def is_url(path):
    """判断输入是否为网络地址"""
    parsed = urlparse(path)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def normalize_swagger_url(url):
    """如果URL没有路径或路径仅为/，自动拼接/v2/api-docs"""
    parsed = urlparse(url)
    path = parsed.path
    if not path or path == '/':
        return url.rstrip('/') + '/v2/api-docs'
    return url


def fetch_json(source):
    """从本地文件或网络地址获取JSON数据"""
    if is_url(source):
        url = normalize_swagger_url(source)
        if url != source:
            print(f"[提示] 自动补全Swagger地址: {source} -> {url}")
        try:
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=30) as response:
                data = response.read().decode('utf-8')
                return json.loads(data)
        except HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.reason} — {url}")
        except URLError as e:
            raise RuntimeError(f"无法访问 URL: {e.reason} — {url}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"URL返回内容不是有效的JSON: {e} — {url}")
    else:
        with open(source, 'r', encoding='utf-8') as f:
            return json.load(f)


# 递归遍历JSON对象，找到所有description字段
def find_all_descriptions(obj, descriptions=None):
    if descriptions is None:
        descriptions = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == 'description' and isinstance(value, str):
                descriptions.append(value)
            else:
                find_all_descriptions(value, descriptions)
    elif isinstance(obj, list):
        for item in obj:
            find_all_descriptions(item, descriptions)

    return descriptions

# 处理单个description字符串
def process_description(desc):
    if not desc:
        return None, False

    # 按冒号拆分
    parts = desc.split(':')
    if len(parts) < 3:
        return None, False

    # 清理各部分
    cleaned_parts = [part.strip() for part in parts]

    # 提取各部分
    part1 = cleaned_parts[1]
    part2 = cleaned_parts[2]
    other_parts = [p for p in cleaned_parts[3:] if p]

    # 重组
    result_parts = [part1, part2] + other_parts
    result_line = '|'.join(result_parts)

    # 判断是否为null
    is_null = (part1 == 'null')

    return result_line, is_null

# 解析Swagger JSON并生成替换规则
def generate_replacement_rules(json_source, output_dir):
    # 读取JSON（支持本地文件或网络URL）
    data = fetch_json(json_source)

    # 找到所有description字段
    all_descriptions = find_all_descriptions(data)

    # 处理所有description
    replace_dict = {}  # 使用字典去重，键为第二个字符串
    not_found_lines = []

    for desc in all_descriptions:
        processed, is_null = process_description(desc)
        if processed:
            if is_null:
                not_found_lines.append(processed)
            else:
                # 提取第二个字符串作为去重键
                parts = processed.split('|')
                if len(parts) >= 2:
                    second_part = parts[1]
                    # 只保留最后一个出现的相同第二个字符串的条目
                    replace_dict[second_part] = processed

    # 将去重后的结果转换为列表
    replace_rules = []
    for line in replace_dict.values():
        parts = line.split('|')
        if len(parts) >= 2:
            old_str = parts[0].strip()
            new_str = parts[1].strip()
            replace_rules.append((old_str, new_str))

    # 写入中间文件（输出到目标目录）
    replace_txt = os.path.join(output_dir, 'replace.txt')
    not_found_txt = os.path.join(output_dir, 'not_found.txt')

    with open(replace_txt, 'w', encoding='utf-8') as f:
        for line in replace_dict.values():
            f.write(line + '\n')

    with open(not_found_txt, 'w', encoding='utf-8') as f:
        for line in not_found_lines:
            f.write(line + '\n')

    print(f"成功处理 {len(all_descriptions)} 个description字段")
    print(f"- 写入 {replace_txt}: {len(replace_dict.values())} 行")
    print(f"- 写入 {not_found_txt}: {len(not_found_lines)} 行")

    return replace_rules

# 定义要跳过的目录和文件
exclude_dirs = ['.git', '.gradle', '.idea', 'build', 'gradle']
exclude_extensions = ['.jar', '.class', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.bin', '.zip', '.rar', '.exe']

def apply_replacement(content, old_str, new_str, use_word_boundary):
    """执行单次替换，返回替换后的内容和替换次数"""
    if use_word_boundary:
        # 使用正则词边界匹配，避免部分字符串误替换
        # 对 old_str 中的正则特殊字符进行转义
        escaped = re.escape(old_str)
        pattern = r'\b' + escaped + r'\b'
        new_content, count = re.subn(pattern, new_str, content)
        return new_content, count
    else:
        count = content.count(old_str)
        if count > 0:
            return content.replace(old_str, new_str), count
        return content, 0

# 递归遍历目录，处理所有文本文件
def process_directory(directory, rules, dry_run=False, use_word_boundary=True):
    modified_files = []
    total_replacements = 0

    for root, dirs, files in os.walk(directory):
        # 跳过不需要处理的目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for file in files:
            # 跳过不需要处理的文件
            if any(file.endswith(ext) for ext in exclude_extensions):
                continue
            # 排除替换规则文件
            if file in ['replace.txt', 'not_found.txt']:
                continue

            file_path = os.path.join(root, file)
            try:
                # 读取文件内容
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 执行替换
                new_content = content
                file_changes = []
                file_replacement_count = 0

                for old_str, new_str in rules:
                    replaced_content, count = apply_replacement(new_content, old_str, new_str, use_word_boundary)
                    if count > 0:
                        new_content = replaced_content
                        file_changes.append(f"  '{old_str}' -> '{new_str}' ({count}处)")
                        file_replacement_count += count

                # 如果内容有修改
                if file_changes:
                    total_replacements += file_replacement_count
                    modified_files.append({
                        'path': file_path,
                        'changes': file_changes,
                        'count': file_replacement_count
                    })

                    if dry_run:
                        print(f"[预览] {file_path}")
                        for change in file_changes:
                            print(change)
                    else:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f"[已更新] {file_path} ({file_replacement_count}处替换)")
            except Exception as e:
                print(f"[错误] 处理文件失败 {file_path}: {e}")

    return modified_files, total_replacements

# 主函数
def main():
    # 创建参数解析器
    parser = argparse.ArgumentParser(
        description='Swagger接口替换工具 - 从Swagger JSON提取description并批量替换文件内容'
    )

    # 添加参数
    parser.add_argument('-j', '--json', required=True, help='Swagger JSON文件路径或网络URL（支持 http/https）')
    parser.add_argument('-d', '--directory', required=True, help='要进行替换操作的目录路径')
    parser.add_argument('--dry-run', action='store_true',
                        help='预览模式：只显示会替换的内容，不修改实际文件')
    parser.add_argument('--no-word-boundary', action='store_true',
                        help='禁用词边界匹配（默认开启）。禁用后使用简单字符串匹配，可能误替换子字符串')

    # 解析参数
    args = parser.parse_args()

    # 获取用户提供的路径
    json_path = args.json
    target_dir = args.directory
    dry_run = args.dry_run
    use_word_boundary = not args.no_word_boundary

    # 验证路径
    if not is_url(json_path) and not os.path.exists(json_path):
        print(f"错误：Swagger JSON文件不存在 - {json_path}")
        return

    if not os.path.isdir(target_dir):
        print(f"错误：目标目录不存在 - {target_dir}")
        return

    # 生成替换规则
    print("=" * 50)
    print("开始从Swagger JSON提取并生成替换规则...")
    print("=" * 50)
    rules = generate_replacement_rules(json_path, target_dir)
    print(f"生成了 {len(rules)} 条替换规则")

    if len(rules) == 0:
        print("未提取到任何替换规则，请检查Swagger JSON中的description格式")
        return

    # 显示替换规则摘要
    print("\n替换规则摘要（前10条）：")
    for i, (old_str, new_str) in enumerate(rules[:10]):
        print(f"  {i+1}. '{old_str}' -> '{new_str}'")
    if len(rules) > 10:
        print(f"  ... 共 {len(rules)} 条规则")

    # 处理目标目录
    mode_str = "[预览模式]" if dry_run else "[实际替换]"
    boundary_str = "词边界匹配" if use_word_boundary else "简单字符串匹配"
    print(f"\n{'=' * 50}")
    print(f"开始对目录进行替换操作 {mode_str} ({boundary_str})")
    print(f"{'=' * 50}")

    modified_files, total_replacements = process_directory(target_dir, rules, dry_run, use_word_boundary)

    # 输出统计
    print(f"\n{'=' * 50}")
    print("操作完成！")
    print(f"{'=' * 50}")
    print(f"受影响文件数: {len(modified_files)}")
    print(f"总替换次数: {total_replacements}")

    if dry_run:
        print("\n⚠️  当前为预览模式，未修改任何文件。")
        print("   确认无误后，去掉 --dry-run 参数执行实际替换。")

    print(f"\n规则文件已保存到:")
    print(f"  {os.path.join(target_dir, 'replace.txt')}")
    print(f"  {os.path.join(target_dir, 'not_found.txt')}")

if __name__ == "__main__":
    main()
