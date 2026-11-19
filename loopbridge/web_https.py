# SPDX-License-Identifier: Apache-2.0
"""Fixed inspection and effect policy for authorized top-level HTTPS documents."""
import datetime
import json
import os
from urllib.parse import urlsplit

if __package__:
    from .https_egress import https_url
    from .web_native import ELEMENT, WebError, member
else:
    from https_egress import https_url
    from web_native import ELEMENT, WebError, member

INSPECT = r"""
const cut = (s,n=100) => String(s || "").trim().slice(0,n);
const visible = e => e.getClientRects().length && getComputedStyle(e).visibility === "visible"
  && !e.closest("[inert],[aria-hidden=true]");
const candidates = document.querySelectorAll("input,textarea,select,button,a,[role],iframe");
const controls = [];
for (const e of candidates) {
  if (controls.length >= 48 || !visible(e) || e.disabled || e.readOnly
      || e.getAttribute("aria-disabled") === "true") continue;
  let role = "", kind = "", value = "", options = [], destination = "";
  if (e.matches("input") && ["text","search","number","date","email","tel","url"].includes(e.type)
      && !["one-time-code","current-password","new-password","cc-number"].includes(e.autocomplete)) {
    role = e.type === "search" ? "searchbox" : e.type === "number" ? "spinbutton" : "textbox";
    kind = e.type; value = cut(e.value,160);
  } else if (e.matches("textarea")) {
    role = "textbox"; kind = "textarea"; value = cut(e.value,160);
  } else if (e.matches("select") && !e.multiple && e.options.length <= 24) {
    role = "combobox"; kind = "select"; value = cut(e.value);
    options = Array.from(e.options).filter(o => !o.disabled && !o.parentElement.disabled)
      .map(o => ({label:cut(o.label), value:cut(o.value), node:o}));
  } else if (e.matches("input") && ["checkbox","radio"].includes(e.type)) {
    role = e.type; kind = "toggle"; value = String(e.checked);
  } else if (e.matches("button,input[type=submit]")) {
    role = "button"; kind = e.type === "button" ? "control" : "submit";
  } else if (e.matches("a[href]") && !e.target && !e.hasAttribute("download")) {
    role = "link"; kind = "link"; destination = e.href;
  } else if (["button","option","checkbox","radio","combobox","tab"].includes(e.getAttribute("role"))) {
    role = e.getAttribute("role"); kind = "control";
  } else if (e.matches("iframe")) {
    role = "iframe"; kind = "frame";
  } else continue;
  const labelled = (e.getAttribute("aria-labelledby") || "").split(/\s+/)
    .map(id => document.getElementById(id)?.innerText).filter(Boolean).join(" ");
  const labels = Array.from(e.labels || []).map(label=>label.innerText).join(" ");
  const group = e.closest("fieldset")?.querySelector("legend")?.innerText;
  const nearby = e.parentElement?.querySelector("label")?.innerText;
  const name = cut(e.getAttribute("aria-label") || labelled || labels || e.innerText
    || e.getAttribute("placeholder") || e.title || nearby || group || e.name || kind);
  const state = [e.getAttribute("aria-expanded"),e.getAttribute("aria-selected"),
    e.getAttribute("aria-checked")].map(x=>cut(x,10));
  controls.push({node:e,role,kind,name,value,options,destination,state,
    required:!!e.required,valid:!e.willValidate || e.validity.valid});
}
return {document:document.documentElement,url:location.href,title:cut(document.title),
        ready:document.readyState !== "loading", controls,
        notices:Array.from(document.querySelectorAll("[role=alert],[role=status],[aria-live]"))
          .filter(visible).slice(0,8).map(node=>cut(node.innerText,160)).filter(Boolean),
        headings:Array.from(document.querySelectorAll("h1,h2,[role=heading]"))
          .filter(visible).slice(0,6).map(node=>cut(node.innerText,120)).filter(Boolean),
        truncated:controls.length === 48};
"""

SET_FIELD = r"""
const [e,kind,value] = arguments;
if (!e.isConnected || e.disabled || e.readOnly ||
    (kind === "textarea" ? e.tagName !== "TEXTAREA" : e.tagName !== "INPUT" || e.type !== kind))
  return false;
const prototype = kind === "textarea" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
Object.getOwnPropertyDescriptor(prototype, "value").set.call(e, value);
if (e.value !== value) return false;
e.dispatchEvent(new Event("input", {bubbles:true}));
e.dispatchEvent(new Event("change", {bubbles:true}));
return true;
"""


def hosts():
    return frozenset(json.loads(os.environ.get('LOOPBRIDGE_HTTPS_HOSTS', '[]')))


def allowed(url):
    try:
        return https_url(url, hosts())
    except ValueError:
        raise WebError('web_destination_denied') from None


def public_url(url):
    uri = urlsplit(url)
    return uri._replace(query='', fragment='').geturl()


def snapshot(session):
    if len(session.unwrap(session.call('WebDriver:GetWindowHandles'))) != 1:
        raise WebError('web_window_ambiguous')
    url = session.unwrap(session.call('WebDriver:GetCurrentURL'))
    allowed(url)
    result = session.unwrap(session.call('WebDriver:ExecuteScript', {'script': INSPECT, 'args': []}))
    if not result['ready'] or result['url'] != url:
        raise WebError('web_document_unstable')
    rows = []
    for node in result['controls']:
        row = {key: node[key] for key in ('role', 'kind', 'name', 'value', 'state', 'destination', 'required', 'valid')}
        if row['destination']:
            try:
                allowed(row['destination'])
            except WebError:
                row['destination'] = ''
        row['key'] = node['node'][ELEMENT]
        row['options'] = [dict(label=o['label'], value=o['value'], key=o['node'][ELEMENT])
                          for o in node['options']]
        rows.append(row)
    return dict(document=result['document'][ELEMENT], url=url, title=result['title'],
                controls=rows, truncated=result['truncated'], page='https', tables=[],
                notices=result['notices'], headings=result['headings'])


def field_value(kind, value):
    if (not isinstance(value, str) or len(value) > 120
            or any(ord(c) < 32 for c in value) or kind not in
            ('text', 'search', 'number', 'date', 'email', 'tel', 'url', 'textarea')):
        raise WebError('web_field_unsupported')
    try:
        if kind == 'date' and datetime.date.fromisoformat(value).isoformat() != value:
            raise ValueError
        if kind == 'number' and (not value.isascii() or not value.isdecimal()):
            raise ValueError
    except ValueError:
        raise WebError('web_field_value_invalid') from None


def execute(session, request, local_snapshot):
    op = request['operation']
    if op == 'inspect_external':
        return snapshot(session)
    if op == 'navigate_https':
        url = request['destination']
        allowed(url)
        try:
            before = snapshot(session)
        except WebError:
            before = local_snapshot(session)
        if (before['document'], before['url']) != (request['document'], request['url']):
            raise WebError('stale_web_document')
        if not request.get('preview'):
            session.call('WebDriver:Navigate', {'url': url})
        return dict(url=url)
    state = snapshot(session)
    row = member(state, request)
    kind = row['kind']
    key = row['key']
    method, value = '', request.get('value')
    if op == 'external_text':
        field_value(kind, value)
        method = 'text'
    elif op == 'external_select' and kind == 'select':
        choices = [option['key'] for option in row['options'] if option['value'] == value]
        if len(choices) != 1:
            raise WebError('web_option_ambiguous')
        method, key = 'click', choices[0]
    elif op == 'external_submit' and kind == 'submit':
        if any(item['required'] and not item['valid'] for item in state['controls']):
            raise WebError('web_required_field_invalid')
        method = 'click'
    elif op == 'external_activate' and kind in ('link', 'control', 'toggle'):
        if kind == 'link' and not row['destination']:
            raise WebError('web_destination_denied')
        method = 'click'
    else:
        raise WebError('web_effect_requires_qualification')
    result = dict(kind=kind, key=key, value=value, url=row['destination'], before=row['value'],
                  state=row['state'], document=state['document'],
                  notices=state['notices'] if op == 'external_submit' else [],
                  headings=state['headings'] if op == 'external_submit' else [])
    if request.get('preview'):
        return result
    if request.get('expected') != result:
        raise WebError('stale_web_control')
    if method == 'text':
        if not session.unwrap(session.call('WebDriver:ExecuteScript', {
                'script': SET_FIELD, 'args': [{ELEMENT: key}, kind, value]})):
            raise WebError('web_field_changed')
    else:
        session.call('WebDriver:ElementClick', {'id': key})
    return result
