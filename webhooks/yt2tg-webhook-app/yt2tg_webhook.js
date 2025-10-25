var entities = require('@jetbrains/youtrack-scripting-api/entities');
var http = require('@jetbrains/youtrack-scripting-api/http');

exports.rule = entities.Issue.onChange({
  title: 'Issue created – sending webhook',
  guard: function (ctx) { return ctx.issue.becomesReported; },
  action: function (ctx) {
    var issue = ctx.issue;

    // Обчислення читабельного ID
    var prjShort = (issue.project && (issue.project.shortName || issue.project.name)) || '';
    var computedId = '';
    if (issue.idReadable) {
      computedId = issue.idReadable;
    } else if (prjShort && issue.numberInProject != null) {
      computedId = prjShort + '-' + issue.numberInProject;
    } else if (issue.id != null) {
      computedId = String(issue.id);
    }

    var payload = {
      idReadable: computedId,
      summary: issue.summary || '',
      description: issue.description || '',
      url: issue.url || ''
    };

    // Налаштування з app settings
    var baseUrl = (ctx.settings.WEBHOOK_BASE || '').replace(/\/+$/, '');
    var secret  = ctx.settings.WEBHOOK_SECRET;

    if (!baseUrl || !secret) {
      ctx.log('yt2tg: settings missing (baseUrl or secret)');
      return;
    }

    // Відправлення
    var conn = new http.Connection(baseUrl);
    conn.addHeader('Content-Type', 'application/json');
    conn.bearerAuth(secret);

    try {
      var res = conn.postSync('/youtrack', [], JSON.stringify(payload));
      var code = (res && (res.status != null ? res.status : res.responseCode));
      ctx.log('yt2tg: POST /youtrack status=' + code + ' body=' + String(res.response).slice(0, 200));
    } catch (e) {
      ctx.log('yt2tg: request failed: ' + e);
      // не кидаємо – щоб не блокувати створення задачі
    }
  },
  requirements: {}
});
