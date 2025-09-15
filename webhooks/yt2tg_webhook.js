// Воркфлоу YouTrack: на створення задачі надсилати коротке повідомлення на бекенд
var entities = require('@jetbrains/youtrack-scripting-api/entities');
var http = require('@jetbrains/youtrack-scripting-api/http');

exports.rule = entities.Issue.onChange({
  title: 'Post new issue to Telegram',
  // Запускати дію лише на подію створення
  guard: function(ctx) {
    return ctx.issue.becomesReported;
  },
  // Зібрати мінімальний пейлоад і надіслати на вебхук бекенда
  action: function(ctx) {
    var issue = ctx.issue;

    // Обчислити читабельний ID навіть коли issue.idReadable ще порожній
    var prjShort = (issue.project && (issue.project.shortName || issue.project.name)) || '';
    var computedId = '';
    if (issue.idReadable) {
      computedId = issue.idReadable;
    } else if (prjShort && (issue.numberInProject !== undefined && issue.numberInProject !== null)) {
      computedId = prjShort + '-' + issue.numberInProject;
    } else if (issue.id) {
      computedId = String(issue.id);
    }

    var payload = {
      idReadable: computedId,
      summary: issue.summary || '',
      description: issue.description || '',
      url: issue.url || ''
    };

    // Вказати базову адресу вебхука (заміни WEBHOOK_URL на свій)
    var conn = new http.Connection('WEBHOOK_URL');
    conn.addHeader('Content-Type', 'application/json');

    conn.postSync('/youtrack', [], JSON.stringify(payload));
  },
  requirements: {}
});
