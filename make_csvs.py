#!/usr/bin/env python3

import collections
import csv
import pathlib
import re
import shutil
import tempfile
import ck2parser
from ck2parser import rootpath
import print_time

def process_provinces(parser, default_tree):
    id_name_map = {}
    defs_path = parser.file('map/' + default_tree['definitions'].val)
    for row in ck2parser.csv_rows(defs_path):
        try:
            id_name_map[row[0]] = row[4]
        except IndexError:
            continue
    prov_title = {}
    for path in parser.files('history/provinces/* - *.txt'):
        number, name = path.stem.split(' - ')
        if id_name_map.get(number) == name:
            the_id = 'PROV{}'.format(number)
            tree = parser.parse_file(path)
            try:
                prov_title[the_id] = tree['title'].val
            except KeyError:
                pass
    return prov_title

def process_regions(parser, default_tree):
    title_region = {}
    path = parser.file('map/' + default_tree['geographical_region'].val)
    tree = parser.parse_file(path)
    for n, v in tree:
        if n.val.startswith('world_') and 'regions' not in v.dictionary:
            assert len(v) == 1
            region = n.val[6:]
            try:
                for x in v['duchies']:
                    title_region[x.val] = region
            except KeyError:
                print(n.val)
                raise
    return title_region

def process_landed_titles(parser, lt_keys, title_region):
    def recurse(tree, liege=None):
        for n, v in tree:
            if ck2parser.is_codename(n.val):
                attrs = {n.val: '', n.val + '_adj': ''}
                for n2, v2 in v:
                    if n2.val in lt_keys:
                        try:
                            value = v2.val
                        except AttributeError:
                            value = ' '.join(s.val for s in v2)
                        attrs[n2.val] = value
                title_attrs[n.val] = attrs
                if liege:
                    title_vassals[liege].append(n.val)
                recurse(v, n.val)
                if n.val[0] == 'd':
                    region = title_region.get(n.val)
                    for vassal in title_vassals[n.val]:
                        rerecurse(vassal, region)
                elif n.val[0] in 'ek':
                    counter = collections.Counter(title_region[t]
                        for t in title_vassals[n.val] if t in title_region)
                    if counter:
                        region = min(counter.items(),
                                     key=lambda x: (-x[1], x[0]))[0]
                        rerecurse(n.val, region)

    def rerecurse(title, region):
        if title not in title_region:
            title_region[title] = region
            for vassal in title_vassals[title]:
                rerecurse(vassal, region)

    title_vassals = collections.defaultdict(list)
    title_attrs = collections.OrderedDict()
    for _, tree in parser.parse_files('common/landed_titles/*'):
        recurse(tree)
    return title_attrs

def process_localisation(parser, title_attrs, prov_title):
    other_locs = {}
    seen = set()
    for path in parser.files('localisation/*', reverse=True):
        for row in ck2parser.csv_rows(path):
            key, value = row[0:2]
            if key not in seen:
                seen.add(key)
                if re.match('[ekdcb]_', key):
                    adj_match = re.match('(.+)_adj(_|$)', key)
                    title = key if not adj_match else adj_match.group(1) 
                elif re.match('PROV\d+', key):
                    if key in prov_title:
                        title = prov_title[key]
                    else:
                        other_locs[key] = value
                        continue
                else:
                    continue
                try:
                    title_attrs[title][key] = value
                except KeyError:
                    pass
    return other_locs

def attrs_sort_key(item, title, lt_keys, cultures):
    key, value = item
    retval = [key in lt_keys, key in cultures]
    if key in lt_keys:
        return True, (item,)
    if key in cultures:
        key = title + '_' + key
    else:
        adj_match = re.fullmatch('(.+)_adj(_.*)', key)
        if adj_match:
            key = adj_match.group(1) + adj_match.group(2) + '_adj'
    return False, (key, item)

def read_prev():
    prev_title_attrs = collections.defaultdict(dict)
    prev_other_locs = {}
    for path in ck2parser.files('*.csv', basedir=(rootpath / 'shv/templates')):
        with path.open(encoding='utf8', newline='') as csvfile:
            reader = csv.reader(csvfile)
            next(reader)
            if 'other_provinces' in path.name:
                for row in reader:
                    key, value = row[:2]
                    prev_other_locs[key] = value
            else:
                for row in reader:
                    title, key, value = row[:3]
                    prev_title_attrs[title][key] = value
    return prev_title_attrs, prev_other_locs

def write_output(title_attrs, title_region, other_locs, prev_title_attrs,
                 prev_other_locs):
    out_row_lists = collections.defaultdict(
        lambda: [['#TITLE', 'KEY', 'VALUE', 'SWMH']])
    for title, pairs in title_attrs.items():
        out_rows = out_row_lists[title_region.get(title)]
        for key, value in pairs:
            prev = prev_title_attrs[title].get(key, '')
            out_rows.append([title, key, prev, value])
    with tempfile.TemporaryDirectory() as td:
        templates_t = pathlib.Path(td)
        for region, out_rows in out_row_lists.items():
            region = region if region else 'titular'
            out_path = templates_t / 'zz~_SHV_titles_{}.csv'.format(region)
            with out_path.open('w', encoding='utf8', newline='') as csvfile:
                csv.writer(csvfile).writerows(out_rows)
        out_path = templates_t / 'zz~_SHV_provinces_other.csv'
        out_rows = [['#KEY', 'VALUE', 'SWMH']]
        for key, value in other_locs:
            prev = prev_other_locs.get(key, '')
            out_rows.append([key, prev, value])
        with out_path.open('w', encoding='utf8', newline='') as csvfile:
            csv.writer(csvfile).writerows(out_rows)
        templates = rootpath / 'shv/templates'
        if templates.exists():
            shutil.rmtree(str(templates))
        shutil.copytree(str(templates_t), str(templates))

@print_time.print_time
def main():
    parser = ck2parser.SimpleParser(rootpath / 'SWMH-BETA/SWMH')
    default_tree = parser.parse_file(parser.file('map/default.map'))
    prov_title = process_provinces(parser, default_tree)
    title_region = process_regions(parser, default_tree)
    lt_keys = {'title', 'title_female', 'foa', 'title_prefix', 'short_name',
        'name_tier', 'location_ruler_title', 'dynasty_title_names',
        'male_names'}
    cultures = set(ck2parser.get_cultures(parser, groups=False))
    title_attrs = process_landed_titles(parser, lt_keys | cultures,
                                        title_region)
    other_locs = process_localisation(parser, title_attrs, prov_title)
    prev_title_attrs, prev_other_locs = read_prev()
    for title, prev_attrs in prev_title_attrs.items():
        title_attrs[title] = dict(((k, '') for k in prev_attrs),
                                  **title_attrs[title])
    for title, attrs in title_attrs.items():
        title_attrs[title] = sorted(attrs.items(),
            key=lambda x: attrs_sort_key(x, title, lt_keys, cultures))
    other_locs = dict(((k, '') for k in prev_other_locs), **other_locs)
    other_locs = sorted(other_locs.items(), key=lambda x: int(x[0][4:]))
    write_output(title_attrs, title_region, other_locs, prev_title_attrs,
                 prev_other_locs)

if __name__ == '__main__':
    main()
