# SPDX-License-Identifier: Apache-2.0
"""Private browser inspection of immutable local pages with bounded native effects."""
import re
from urllib.parse import parse_qsl, urlsplit

ROOT = 'file:///fixture/site/'
PAGES = dict(home='index.html', search='search.html', results='results.html',
             review='review.html', confirmation='confirmation.html')
TEXT = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ./_-]{0,119}')
ELEMENT = 'element-6066-11e4-a52e-4f735466cecf'


class WebError(ValueError):
    pass


# This fixed inspector returns Gecko element references, never client selectors.
# It reads the document and form model. Navigation and values use native commands.
INSPECT = r"""
const visible = e => e.getClientRects().length && getComputedStyle(e).visibility === "visible";
const short = (s, n = 100) => String(s || "").trim().slice(0, n);
const controls = [];
const candidates = [...document.querySelectorAll("input, textarea, select, button, a")];
for (const node of candidates.slice(0, 48)) {
  if (!visible(node) || node.disabled || node.readOnly || node.closest("[inert],[aria-hidden=true]"))
    continue;
  let role, value = "", options = [], destination = "", fields = [];
  if ((node.tagName === "INPUT" && ["text", "search"].includes(node.type)) || node.tagName === "TEXTAREA") {
    role = "textbox";
    value = String(node.value).slice(0,120);
  } else if (node.tagName === "SELECT" && !node.multiple && node.options.length <= 12) {
    role = "combobox";
    value = short(node.value);
    options = [...node.options].filter(item => !item.disabled && !item.parentElement.disabled)
      .map(item => ({label:short(item.label), value:short(item.value), node:item}));
  } else if (node.tagName === "BUTTON" && node.type === "submit" && node.form) {
    if ((node.getAttribute("formmethod") || node.form.method).toLowerCase() !== "get" ||
        node.getAttribute("formtarget") || node.form.target)
      continue;
    if ([...node.form.elements].some(e => e.name && !e.disabled &&
        !["text","search","select-one","textarea","submit"].includes(e.type))) continue;
    role = "button";
    destination = node.hasAttribute("formaction") ? node.formAction : node.form.action;
    fields = [...new FormData(node.form, node).entries()].map(([k,v])=>[String(k).slice(0,100),String(v).slice(0,120)]);
  } else if (node.tagName === "A" && node.hasAttribute("href") && !node.target && !node.hasAttribute("download")) {
    role = "link";
    destination = node.href;
  } else continue;
  const labels = [...(node.labels || [])].map(label => label.innerText).join(" ");
  const name = short(node.getAttribute("aria-label") || labels || node.innerText);
  if (!name) continue;
  controls.push({node,role,name,value,options,destination,fields});
}
const tables = [...document.querySelectorAll("table")].slice(0,3).map(table => ({
  name: short(table.getAttribute("aria-label") || table.caption?.innerText),
  headers: [...(table.tHead?.rows[0]?.cells || [])].slice(0,10).map(c => short(c.innerText)),
  rows: [...table.tBodies].flatMap(body => [...body.rows]).slice(0,24)
     .map(r => [...r.cells].slice(0,10).map(c => short(c.innerText))),
  truncated: table.rows.length > 25
}));
return { document:document.documentElement, url:location.href, title:short(document.title),
  ready:document.readyState !== "loading" && (!location.pathname.endsWith("/results.html")
         || document.documentElement.dataset.resultsReady === "true"),
  truncated:candidates.length > 48, controls, tables };
"""


def page_of(url):
    uri = urlsplit(url)
    if (uri.scheme != 'file' or uri.netloc or uri.fragment or len(uri.query) > 1024
            or not uri.path.startswith('/fixture/site/')):
        raise WebError('web_destination_denied')
    filename = uri.path.removeprefix('/fixture/site/')
    for page, path in PAGES.items():
        if filename == path:
            return page
    raise WebError('web_destination_denied')


def snapshot(session):
    if len(session.unwrap(session.call('WebDriver:GetWindowHandles'))) != 1:
        raise WebError('web_window_ambiguous')
    url = session.unwrap(session.call('WebDriver:GetCurrentURL'))
    page = page_of(url)
    result = session.unwrap(session.call('WebDriver:ExecuteScript',
                                        {'script': INSPECT, 'args': []}))
    if result['url'] != url or not result['ready']:
        raise WebError('web_document_unstable')
    document = result['document'][ELEMENT]
    controls = []
    for control in result['controls']:
        destination = control['destination']
        if destination:
            try:
                page_of(destination)
            except WebError:
                continue
        options = [dict(label=item['label'], value=item['value'], key=item['node'][ELEMENT])
                   for item in control['options']]
        controls.append(dict(key=control['node'][ELEMENT], role=control['role'], name=control['name'],
                             value=control['value'], options=options, destination=destination,
                             fields=control['fields']))
    return dict(document=document, url=url, page=page, title=result['title'], controls=controls,
                tables=result['tables'], truncated=result['truncated'])


def member(state, proof):
    if (state['document'], state['url']) != (proof['document'], proof['url']):
        raise WebError('stale_web_document')
    matches = [row for row in state['controls'] if row['key'] == proof['key']]
    if len(matches) != 1:
        raise WebError('stale_web_control')
    row = matches[0]
    if (row['role'], row['name']) != (proof['role'], proof['name']):
        raise WebError('stale_web_control')
    return row


def exact_fields(uri, fields):
    try:
        return sorted(parse_qsl(urlsplit(uri).query, keep_blank_values=True, max_num_fields=24)) == sorted(
            tuple(field) for field in fields)
    except ValueError:
        return False


def plan(state, request):
    operation = request['operation']
    if operation == 'navigate':
        if (state['document'], state['url']) != (request['document'], request['url']):
            raise WebError('stale_web_document')
        if request['page'] not in PAGES or request['page'] in ('results', 'confirmation'):
            raise WebError('web_destination_denied')
        url = ROOT + PAGES[request['page']]
        if state['url'] == url:
            raise WebError('no_change')
        return dict(url=url, page=request['page'], fields=[])
    row = member(state, request)
    if operation == 'text' and row['role'] == 'textbox':
        value = request['value']
        if not TEXT.fullmatch(value):
            raise WebError('web_text_denied')
        if row['value'] == value:
            raise WebError('no_change')
        return dict(value=value, key=row['key'], clear=bool(row['value']))
    if operation == 'select' and row['role'] == 'combobox':
        choices = [option for option in row['options'] if option['value'] == request['value']]
        if len(choices) != 1:
            raise WebError('web_option_unavailable_or_ambiguous')
        if row['value'] == request['value']:
            raise WebError('no_change')
        return dict(value=request['value'], key=choices[0]['key'])
    if operation == 'activate' and row['role'] in ('button', 'link'):
        destination = row['destination']
        return dict(url=destination, page=page_of(destination), fields=row['fields'], key=row['key'])
    raise WebError('web_operation_denied')


def execute(session, request):
    state = snapshot(session)
    if request['operation'] == 'inspect':
        return state
    expected = plan(state, request)
    if request.get('preview') is True:
        return expected
    if expected != request.get('expected'):
        raise WebError('web_precondition_changed')
    operation = request['operation']
    if operation == 'navigate':
        session.call('WebDriver:Navigate', {'url': expected['url']})
    elif operation == 'text':
        if expected['clear']:
            session.call('WebDriver:ElementClear', {'id': expected['key']})
        session.call('WebDriver:ElementSendKeys', {'id': expected['key'], 'text': expected['value']})
    else:
        session.call('WebDriver:ElementClick', {'id': expected['key']})
    return {}
