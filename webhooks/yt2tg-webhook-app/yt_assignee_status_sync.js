var entities = require('@jetbrains/youtrack-scripting-api/entities');

// логіни сервісних акаунтів (бот, admin тощо)  // не призначати їх автоматично
var SERVICE_LOGINS = ['admin', 'youtrack-bot'];

exports.rule = entities.Issue.onChange({
  title: 'Синхронізація: Виконавець ↔ Статус "В роботі"',
  guard: function (ctx) {
    var issue = ctx.issue;

    // Змінився виконавець і тепер він заданий
    var assigneeChanged = issue.fields.isChanged(ctx.Assignee) && !!issue.fields.Assignee;

    // "Статус" саме "В роботі" (точний перехід)
    var becameInProgress =
      ctx.Status && ctx.Status.InProgress &&
      issue.fields.becomes(ctx.Status, ctx.Status.InProgress);

    // fallback на випадок різних назв у бандлі
    if (!becameInProgress && issue.fields.isChanged(ctx.Status)) {
      var s = issue.fields.Status;
      var name = s && s.name ? String(s.name).toLowerCase() : '';
      var loc  = s && s.localizedName ? String(s.localizedName).toLowerCase() : '';
      becameInProgress = (name === 'в роботі' || name === 'in progress' || loc === 'в роботі');
    }

    // не запускати гілку призначення для сервісних акторів
    var actor = ctx.currentUser;
    var login = actor && actor.login ? String(actor.login) : '';
    var isService = SERVICE_LOGINS.indexOf(login) !== -1;

    // працюємо, якщо сталася хоч одна з подій:
    // - змінився виконавець
    // - статус став "В роботі" і це зробив НЕ сервісний користувач
    return assigneeChanged || (becameInProgress && !isService);
  },

  action: function (ctx) {
    var issue = ctx.issue;
    var actor = ctx.currentUser;
    var assignee = issue.fields.Assignee;

    // Якщо змінився виконавець → гарантуємо статус "В роботі"
    if (ctx.issue.fields.isChanged(ctx.Assignee) && !!assignee) {
      // ставимо лише якщо ще не "В роботі"
      if (!(ctx.Status && ctx.Status.InProgress && issue.fields.Status === ctx.Status.InProgress)) {
        if (ctx.Status && ctx.Status.InProgress) {
          issue.fields.Status = ctx.Status.InProgress;  // ставить "В роботі"
        } else {
          // fallback через пошук у бандлі
          var field = issue.project.fields.Status;
          if (field && field.bundle && field.bundle.values) {
            var target = field.bundle.values.find(function (v) {
              var n1 = (v && v.name) ? v.name.toLowerCase() : '';
              var n2 = (v && v.localizedName) ? v.localizedName.toLowerCase() : '';
              return n1 === 'в роботі' || n1 === 'in progress' || n2 === 'в роботі';
            });
            if (target) issue.fields.Status = target;
          }
        }
      }
    }

    // Якщо "Статус" став "В роботі" (і це не сервісний користувач) → призначаємо поточного
    var becameInProgress =
      ctx.Status && ctx.Status.InProgress &&
      issue.fields.becomes(ctx.Status, ctx.Status.InProgress);

    if (becameInProgress) {
      var login = actor && actor.login ? String(actor.login) : '';
      var isService = SERVICE_LOGINS.indexOf(login) !== -1;

      if (!isService) {
        if (!assignee || assignee.login !== actor.login) {
          issue.fields.Assignee = actor;  // призначає того, хто перевів у "В роботі"
        }
      }
    }
  },

  requirements: {
    Status: {
      type: entities.State.fieldType,
      name: 'Статус',
      InProgress: { name: 'В роботі' }
    },
    Assignee: { type: entities.User.fieldType }
  }
});
