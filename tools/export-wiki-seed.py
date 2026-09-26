#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Docus 文档站的 content/ 目录导出成个人站（D:\\Web）可用的种子数据。

输出：D:\\Web\\admin\\wiki_seed.json
结构：
{
  "generated_at": "...",
  "groups": [
    {
      "slug": "snowygems", "title": "SnowyGems", "icon": "gem",
      "desc": "…", "sort": 1,
      "pages": [
        {"slug": "getting-started", "title": "安装与快速上手",
         "nav": "安装与快速上手", "icon": "rocket", "desc": "…", "content": "…", "sort": 1}
      ]
    }
  ]
}

用法：python tools/export-wiki-seed.py [--content 目录] [--out 文件]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

# 目录名形如 1.snowygems / 5.Companions-Max；文件名形如 4.runes.md
NUM_PREFIX = re.compile(r'^(\d+)\.(.*)$')

# Lucide 图标名 -> 个人站内置图标名（个人站不引外部图标库，全部手写 SVG）
ICON_MAP = {
    'rocket': 'rocket',
    'gem': 'gem',
    'bell-ring': 'bell',
    'book-open': 'book',
    'database': 'database',
    'git-compare': 'compare',
    'hammer': 'hammer',
    'hand-heart': 'heart',
    'history': 'history',
    'languages': 'languages',
    'layout-grid': 'grid',
    'megaphone': 'megaphone',
    'package-plus': 'package',
    'panels-top-left': 'layout',
    'paw-print': 'paw',
    'pencil': 'pencil',
    'scissors': 'scissors',
    'shield-check': 'shield',
    'shield-alert': 'shield',
    'sparkles': 'sparkles',
    'terminal': 'terminal',
    'unplug': 'unplug',
    'wrench': 'wrench',
    'zap': 'zap',
    'info': 'info',
    'lightbulb': 'lightbulb',
    'triangle-alert': 'warning',
    'gauge': 'gauge',
    'code': 'code',
    'file-code-2': 'code',
    'bug': 'bug',
    'arrow-right': 'arrow',
}

# 项目兜底图标（navigation.yml 没写或写不认识时用）
FALLBACK_GROUP_ICON = 'book'

# 分类/插件 slug 的中文显示名（navigation.yml 里只有 title，够用）
DEFAULT_DESC = {
    'snowygems': '宝石镶嵌系统：把宝石镶到装备上获得属性、附魔与常驻 BUFF，宝石还能带主动技能。',
    'snow-welcome': '新人欢迎：新玩家首次进服全服广播可点击的欢迎消息，欢迎他的玩家获得金币、点券或自定义命令奖励。',
    'snow-enchantsp': '附魔剥离：把装备上的附魔揭下来变成附魔书，支持金币 / 点券 / 经验三种支付组合与按附魔单独定价。',
    'kbbstoper': '论坛顶帖奖励：检测苦力怕论坛宣传帖的顶帖记录，玩家绑定论坛账号后顶帖即可在游戏内领奖。',
    'companions-max': '随行宠物与养成系统：隐形盔甲架组合头颅和装备，提供商店、中文独立 GUI、管理员游戏内编辑器与命令补全。',
}

ICON_LINE = re.compile(r'^\s*icon:\s*(.+?)\s*$')
TITLE_LINE = re.compile(r'^\s*title:\s*(.+?)\s*$')


def clean_scalar(raw):
    """去掉 YAML 标量两端的引号"""
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
    return s


def norm_icon(name):
    """i-lucide-xxx -> 个人站图标名"""
    if not name:
        return ''
    n = name.strip()
    if n.startswith('i-lucide-'):
        n = n[len('i-lucide-'):]
    elif n.startswith('i-'):
        n = n[2:]
    return ICON_MAP.get(n, '')


def split_front(text):
    """拆出 YAML frontmatter（只做扁平解析，够用）与正文"""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if not text.startswith('---'):
        return {}, text
    end = text.find('\n---', 3)
    if end < 0:
        return {}, text
    head = text[3:end]
    body = text[end + 4:]
    return head, body.lstrip('\n')


def find_key(head, key):
    """在 frontmatter 里找 key（支持 seo: 下的同名缩进键）"""
    for line in head.split('\n'):
        m = re.match(r'^(\s*)' + key + r':\s*(.*)$', line)
        if m:
            val = clean_scalar(m.group(2))
            indent = len(m.group(1))
            if val == '':
                # 取该键下面更深缩进的第一个非空值（如 seo: \n  title: xxx）
                idx = head.split('\n').index(line)
                for sub in head.split('\n')[idx + 1:]:
                    if not sub.strip():
                        continue
                    sub_indent = len(sub) - len(sub.lstrip())
                    if sub_indent <= indent:
                        break
                    m2 = re.match(r'^\s*[\w-]+:\s*(.+)$', sub)
                    if m2:
                        return clean_scalar(m2.group(1))
                return ''
            return val
    return ''


def parse_nav(nav_text):
    """navigation.yml：取 title 与 icon"""
    head = nav_text
    title = find_key(head, 'title')
    icon = norm_icon(find_key(head, 'icon'))
    return title, icon


def scan_dir(path):
    """返回 (slug, sort, dirname)；目录名 1.snowygems -> ('snowygems', 1)"""
    name = os.path.basename(path)
    m = NUM_PREFIX.match(name)
    if m:
        return m.group(2), int(m.group(1)), name
    return name, 999, name


def scan_file(name):
    """1.getting-started.md -> ('getting-started', 1)"""
    base = name[:-3] if name.lower().endswith('.md') else name
    m = NUM_PREFIX.match(base)
    if m:
        return m.group(2), int(m.group(1))
    return base, 999


def collect(content_dir):
    groups = []
    for entry in sorted(os.listdir(content_dir)):
        sub = os.path.join(content_dir, entry)
        if not os.path.isdir(sub):
            continue
        slug, gsort, dirname = scan_dir(sub)
        nav_file = os.path.join(sub, '.navigation.yml')
        title, icon = slug, ''
        if os.path.isfile(nav_file):
            with open(nav_file, encoding='utf-8') as f:
                title_raw, icon = parse_nav(f.read())
                title = title_raw or slug
        pages = []
        for fname in sorted(os.listdir(sub)):
            if not fname.lower().endswith('.md'):
                continue
            fpath = os.path.join(sub, fname)
            with open(fpath, encoding='utf-8') as f:
                raw = f.read()
            head, body = split_front(raw)
            pslug, psort = scan_file(fname)
            ptitle = find_key(head, 'title')
            if not ptitle:
                # 没有 title 就取正文第一个 H1
                m = re.search(r'^#\s+(.+)$', body, re.M)
                ptitle = m.group(1).strip() if m else pslug
            pdesc = find_key(head, 'description')
            pages.append({
                'slug': pslug,
                'title': ptitle,
                'nav': ptitle,
                'icon': norm_icon(find_key(head, 'icon')),
                'desc': pdesc,
                'content': body.strip() + '\n',
                'sort': psort,
                'src': os.path.relpath(fpath, content_dir).replace('\\', '/'),
            })
        pages.sort(key=lambda p: (p['sort'], p['slug']))
        # 排序号重复（如 1.snowygems 下同时存在 4.menus 与 4.runes）：按名次重排，保证导航稳定
        for i, p in enumerate(pages, start=1):
            p['sort'] = i
        groups.append({
            'slug': slug,
            'title': title,
            'icon': icon or FALLBACK_GROUP_ICON,
            'desc': DEFAULT_DESC.get(slug.lower(), ''),
            'sort': gsort,
            'src': dirname,
            'pages': pages,
        })
    groups.sort(key=lambda g: (g['sort'], g['slug']))
    for i, g in enumerate(groups, start=1):
        g['sort'] = i
    return groups


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--content', default=os.path.join(here, '..', 'content'))
    ap.add_argument('--out', default=r'D:\Web\admin\wiki_seed.json')
    args = ap.parse_args()

    content_dir = os.path.abspath(args.content)
    if not os.path.isdir(content_dir):
        print('内容目录不存在：%s' % content_dir, file=sys.stderr)
        return 1

    groups = collect(content_dir)
    data = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': content_dir,
        'groups': groups,
    }
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    total = sum(len(g['pages']) for g in groups)
    print('已导出 %d 个插件 / %d 篇文档 -> %s' % (len(groups), total, out))
    for g in groups:
        print('  %-16s %s (%d 篇)' % (g['slug'], g['title'], len(g['pages'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
