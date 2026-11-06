"""Erzeugt den iPhone-Kurzbefehl „Laufband Watch“ (unsigniertes XML-Plist).

Aufbau nach echten iOS-Exporten (Referenz: viticci/shortcuts-playground-plugin,
HEALTHKIT.md, golden-shortcuts, ToolKit-Metadaten). Signieren auf dem Mac
(die Eingabe muss auf .shortcut enden, sonst „isn't in the correct format“):
    python3 kurzbefehl/make_shortcut.py /tmp/lw.shortcut
    shortcuts sign --mode anyone --input /tmp/lw.shortcut --output kurzbefehl/Laufband-Watch.shortcut
"""
import plistlib
import sys
import uuid

OBJ = "￼"   # Platzhalter für eine Variable im Text


def uid():
    return str(uuid.uuid4()).upper()


def out(u, name):
    return {"OutputUUID": u, "OutputName": name, "Type": "ActionOutput"}


REPEAT_ITEM = {"Type": "Variable", "VariableName": "Repeat Item"}


def tokens(*parts):
    """Text aus Strings und Variablen (dicts) als WFTextTokenString."""
    s, att = "", {}
    for p in parts:
        if isinstance(p, dict):
            att[f"{{{len(s)}, 1}}"] = p
            s += OBJ
        else:
            s += p
    return {"Value": {"string": s, "attachmentsByRange": att},
            "WFSerializationType": "WFTextTokenString"}


def attach(v):
    return {"Value": v, "WFSerializationType": "WFTextTokenAttachment"}


def act(ident, **params):
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{ident}",
            "WFWorkflowActionParameters": params}


def text(u, value):
    return act("gettext", UUID=u, WFTextActionText=value)


def find_health(u, kind):
    """Health-Samples suchen: Typ = kind, Startdatum in den letzten 3 Stunden."""
    return act("filter.health.quantity", UUID=u, WFContentItemFilter={
        "Value": {
            "WFActionParameterFilterPrefix": 1,
            "WFContentPredicateBoundedDate": False,
            "WFActionParameterFilterTemplates": [
                {"Bounded": True, "Operator": 4, "Property": "Type", "Removable": False,
                 "Values": {"Enumeration": {"Value": kind,
                                            "WFSerializationType": "WFStringSubstitutableState"}}},
                # 1001 = „ist in den letzten“, Unit 32 = Stunden (NSCalendarUnitHour)
                {"Bounded": True, "Operator": 1001, "Property": "Start Date", "Removable": True,
                 "Values": {"Number": "3", "Unit": 32}},
            ],
        },
        "WFSerializationType": "WFContentPredicateTableTemplate",
    })


def detail(u, prop):
    return act("properties.health.quantity", UUID=u, WFContentItemPropertyName=prop,
               WFInput=attach(REPEAT_ITEM))


def iso(u, src_uuid, src_name):
    return act("format.date", UUID=u, WFDate=tokens(out(src_uuid, src_name)),
               WFDateFormatStyle="ISO 8601", WFISO8601IncludeTime=True)


def loop(source_uuid, body, line_parts):
    """Für jedes Sample eine Textzeile; danach Zeilen mit Umbruch verbinden."""
    g, end, line, comb = uid(), uid(), uid(), uid()
    acts = [act("repeat.each", GroupingIdentifier=g, WFControlFlowMode=0,
                WFInput=attach(out(source_uuid, "Health Samples")))]
    acts += body
    acts.append(text(line, tokens(*line_parts)))
    acts.append(act("repeat.each", UUID=end, GroupingIdentifier=g, WFControlFlowMode=2))
    acts.append(act("text.combine", UUID=comb, WFTextSeparator="New Lines",
                    text=attach(out(end, "Repeat Results"))))
    return acts, comb


def build():
    person, token, url = uid(), uid(), uid()
    actions = [
        text(person, "Tim"),
        text(token, ""),
        text(url, "http://homeassistant.local:8098/health"),
    ]

    hr = uid()
    actions.append(find_health(hr, "Heart Rate"))
    d_start, f_start, d_val = uid(), uid(), uid()
    a, hr_text = loop(hr, [detail(d_start, "Start Date"), iso(f_start, d_start, "Start Date"),
                           detail(d_val, "Value")],
                      [out(f_start, "Formatted Date"), ";", out(d_val, "Value")])
    actions += a

    st = uid()
    actions.append(find_health(st, "Steps"))
    ds, fs, de, fe, dv, dq = uid(), uid(), uid(), uid(), uid(), uid()
    a, st_text = loop(st, [detail(ds, "Start Date"), iso(fs, ds, "Start Date"),
                           detail(de, "End Date"), iso(fe, de, "End Date"),
                           detail(dv, "Value"), detail(dq, "Source")],
                      [out(fs, "Formatted Date"), ";", out(fe, "Formatted Date"), ";",
                       out(dv, "Value"), ";", out(dq, "Source")])
    actions += a

    def field(key, value):
        return {"WFItemType": 0, "WFKey": tokens(key), "WFValue": value}

    post = uid()
    actions.append(act(
        "downloadurl", UUID=post, Advanced=True, ShowHeaders=True,
        WFURL=tokens(out(url, "Text")), WFHTTPMethod="POST", WFHTTPBodyType="JSON",
        WFHTTPHeaders={"Value": {"WFDictionaryFieldValueItems": [
            field("Authorization", tokens("Bearer ", out(token, "Text")))]},
            "WFSerializationType": "WFDictionaryFieldValue"},
        WFJSONValues={"Value": {"WFDictionaryFieldValueItems": [
            field("person", tokens(out(person, "Text"))),
            field("heart_rate", tokens(out(hr_text, "Combined Text"))),
            field("steps", tokens(out(st_text, "Combined Text"))),
        ]}, "WFSerializationType": "WFDictionaryFieldValue"},
    ))
    actions.append(act("notification", UUID=uid(), WFNotificationActionTitle="Laufband",
                       WFNotificationActionBody=tokens(out(post, "Contents of URL"))))

    def question(index, key, default, prompt):
        return {"ActionIndex": index, "Category": "Parameter", "DefaultValue": default,
                "ParameterKey": key, "Text": prompt}

    return {
        "WFWorkflowActions": actions,
        "WFWorkflowClientVersion": "2700.0.4",
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59511,
                           "WFWorkflowIconStartColor": 4282601983},
        "WFWorkflowImportQuestions": [
            question(0, "WFTextActionText", "Tim",
                     "Dein Name, genau wie in der Laufband-App unter „people“:"),
            question(1, "WFTextActionText", "",
                     "Der health_token aus den Optionen der Laufband-App:"),
            question(2, "WFTextActionText", "http://homeassistant.local:8098/health",
                     "Adresse der Laufband-App (Port 8098, Pfad /health):"),
        ],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": "Laufband Watch",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
    }


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        plistlib.dump(build(), f, fmt=plistlib.FMT_BINARY)
