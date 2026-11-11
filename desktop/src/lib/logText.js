// What a Log row says, in the language selected now. An entry written by
// activityLog.js carries the English text it was stored with (titleKey and
// detailKey are absent on entries from before 1.11.1, and on raw technical
// details such as error messages) plus, when it came from a translatable
// message, the key and values to render it again.
export function logTitle(event, tr) {
  return render(event.titleKey, event.titleVars, event.title, tr);
}

export function logDetail(event, tr) {
  return render(event.detailKey, event.detailVars, event.detail, tr);
}

function render(key, vars, stored, tr) {
  if (!key) return stored;
  const text = tr(key, vars);
  // The translator returns the key itself for one it doesn't know (a key
  // removed in a later version): the stored English is the better answer.
  return text === key ? stored : text;
}
