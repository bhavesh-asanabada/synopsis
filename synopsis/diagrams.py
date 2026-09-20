"""Validate model-generated architecture data and render passive, portable SVG."""
import re
import textwrap
from html import escape


def diagram_svg(data):
    if not isinstance(data, dict):
        raise ValueError('The model did not return an architecture diagram.')
    nodes, edges, groups = data.get('nodes'), data.get('edges', []), data.get('groups', [])
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 60 or not isinstance(edges, list) or len(edges) > 120 or not isinstance(groups, list) or len(groups) > 12:
        raise ValueError('Diagrams support 1–60 components, up to 120 connections and 12 groups.')
    def label(value, limit=120):
        if not isinstance(value, str) or not value.strip() or len(value) > limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):
            raise ValueError('The diagram contains an invalid label.')
        return value.strip()
    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', value):
            raise ValueError('The diagram contains an invalid component ID.')
        return value
    title = label(data.get('title', 'Architecture'), 200)
    clean_groups = []
    for group in groups:
        if not isinstance(group, dict):raise ValueError('Invalid diagram group.')
        clean_groups.append({'id':identifier(group.get('id')), 'label':label(group.get('label'))})
    if len({g['id'] for g in clean_groups}) != len(clean_groups):raise ValueError('Duplicate diagram group IDs.')
    group_ids = {g['id'] for g in clean_groups}
    clean_nodes = []
    for node in nodes:
        if not isinstance(node, dict):raise ValueError('Invalid diagram component.')
        group = node.get('group', '')
        if not isinstance(group,str) or (group and group not in group_ids):raise ValueError('A diagram component refers to an unknown group.')
        clean_nodes.append({'id':identifier(node.get('id')), 'label':label(node.get('label')), 'group':group})
    ids = {n['id'] for n in clean_nodes}
    if len(ids) != len(clean_nodes):raise ValueError('Duplicate diagram component IDs.')
    clean_edges = []
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get('from'),str) or not isinstance(edge.get('to'),str) or edge['from'] not in ids or edge['to'] not in ids:
            raise ValueError('A diagram connection refers to an unknown component.')
        clean_edges.append({'from':edge['from'], 'to':edge['to'], 'label':label(edge['label'], 80) if edge.get('label') else ''})
    # Groups become distinct architecture layers. Ungrouped diagrams use rows of four.
    rows = []
    for group in clean_groups + [{'id':'', 'label':'Components'}]:
        members = [n for n in clean_nodes if n['group'] == group['id']]
        for offset in range(0, len(members), 4):
            rows.append((group['label'], members[offset:offset+4]))
    title_lines=textwrap.wrap(title,70)
    top=80+(len(title_lines)-1)*28
    width, height = 1100, top+20 + len(rows) * 210
    positions = {}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}">',
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#789483"/></marker></defs>',
           f'<rect width="{width}" height="{height}" fill="#fafbf9"/>']
    for line,text in enumerate(title_lines):svg.append(f'<text x="35" y="{45+line*28}" font-family="sans-serif" font-size="24" fill="#224b3d">{escape(text)}</text>')
    for r, (group, members) in enumerate(rows):
        y = top + r * 210
        svg += [f'<rect x="25" y="{y}" width="1050" height="175" rx="12" fill="#f0f4ed" stroke="#dbe5d7"/>',
                f'<text x="42" y="{y+28}" font-family="sans-serif" font-size="13" fill="#60775b">{escape(group)}</text>']
        for c, node in enumerate(members):positions[node['id']] = (45 + c * 260, y + 55)
    for n, edge in enumerate(clean_edges):
        x1,y1 = positions[edge['from']];x2,y2 = positions[edge['to']]
        if edge['from']==edge['to']:
            path=f'M{x1+230} {y1+25} C{x1+260} {y1} {x1+260} {y1+90} {x1+230} {y1+65}'
            tx,ty=x1+245,y1+110
        elif y1 == y2:
            start,end = (x1+115,y1+90),(x2+115,y2+90)
            bend = y1+115+(n%3)*10
            path = f'M{start[0]} {start[1]} C{start[0]} {bend} {end[0]} {bend} {end[0]} {end[1]}'
            tx,ty = (start[0]+end[0])/2,bend+5
        else:
            down = y2>y1
            start,end = (x1+115,y1+(90 if down else 0)),(x2+115,y2+(0 if down else 90))
            mid=(start[1]+end[1])/2
            path=f'M{start[0]} {start[1]} C{start[0]} {mid} {end[0]} {mid} {end[0]} {end[1]}'
            tx,ty=(start[0]+end[0])/2,mid-5
        svg.append(f'<path d="{path}" fill="none" stroke="#789483" stroke-width="1.7" marker-end="url(#arrow)"><title>{escape(edge["label"])}</title></path>')
        if edge['label']:svg.append(f'<text x="{tx}" y="{ty}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#3d6553" stroke="#fafbf9" stroke-width="3" paint-order="stroke">{escape(edge["label"])}</text>')
    for node in clean_nodes:
        x,y=positions[node['id']]
        svg.append(f'<rect x="{x}" y="{y}" width="230" height="90" rx="9" fill="white" stroke="#9cb49a"/>')
        for line,text in enumerate(textwrap.wrap(node['label'], width=27)[:4]):
            svg.append(f'<text x="{x+115}" y="{y+24+line*17}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#27372f">{escape(text)}</text>')
    svg.append('</svg>')
    return {'title':title,'groups':clean_groups,'nodes':clean_nodes,'edges':clean_edges}, ''.join(svg)
