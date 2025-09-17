// Воркфлоу YouTrack: на створення задачі надсилати коротке повідомлення на бекенд із секретом
var entities = require('@jetbrains/youtrack-scripting-api/entities');
var http = require('@jetbrains/youtrack-scripting-api/http');

var WEBHOOK_BASE = 'WEBHOOK_URL'; // без суфікса /youtrack
var SHARED_SECRET = 'WEBHOOK_SECRET'; // має збігатися з WEBHOOK_SECRET_YT на бекенді

exports.rule = entities.Issue.onChange({
  title: 'Post new issue to Telegram with secret',

  guard: function(ctx) {
    // Запускати тільки при створенні
    return ctx.issue.becomesReported;
  },
  action: function(ctx) {
    var issue = ctx.issue;

    // Обчислити читабельний ID навіть коли idReadable ще порожній
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

    // Підготувати підключення та додати заголовки
    var conn = new http.Connection(WEBHOOK_BASE);
    conn.addHeader('Content-Type', 'application/json');
    conn.addHeader('Authorization', 'Bearer ' + SHARED_SECRET); // ключовий заголовок

    // Відправити синхронно на бекенд
    conn.postSync('/youtrack', [], JSON.stringify(payload));
  },
  requirements: {}
});
