"""
郵件工具模塊
- 讀取 EmailConfig 配置
- 生成測試報告 HTML
- 發送郵件（SSL / TLS / 普通）
"""
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  獲取當前激活的郵件配置
# ─────────────────────────────────────────────

def get_active_email_config():
    from apps.core.models import EmailConfig
    cfg = EmailConfig.objects.filter(is_active=True).order_by('-updated_at').first()
    if not cfg:
        return None, '未找到啟用的郵件配置，請先在「郵件配置」中設置'
    return cfg, None


# ─────────────────────────────────────────────
#  測試郵件配置
# ─────────────────────────────────────────────

def test_email_config(config, to_addr: str) -> tuple:
    """發送一封測試郵件，返回 (success, message)"""
    html = """
    <div style="font-family:Arial,sans-serif;padding:20px;max-width:500px">
      <h2 style="color:#4f46e5">✅ API 測試平台 — 郵件配置測試</h2>
      <p>此郵件由系統自動發送，用於驗證郵件配置是否正確。</p>
      <p style="color:#64748b;font-size:12px">發送時間：{time}</p>
    </div>
    """.format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    return _send_mail(config, [to_addr], '【API測試平台】郵件配置測試', html)


# ─────────────────────────────────────────────
#  生成報告 HTML
# ─────────────────────────────────────────────

def build_report_html(report) -> str:
    """將 TestReport 及其結果轉為 HTML 郵件正文"""
    results = list(report.results.all())

    # 進度條色塊
    pr = report.pass_rate
    fr = round(report.failed / report.total * 100, 1) if report.total else 0
    er = round(report.error  / report.total * 100, 1) if report.total else 0

    status_color = '#10b981' if pr == 100 else ('#f59e0b' if pr >= 60 else '#ef4444')
    title_icon   = '✅' if pr == 100 else ('⚠️' if pr >= 60 else '❌')

    # 結果明細行
    rows_html = ''
    for r in results:
        s_color = {'pass': '#10b981', 'fail': '#ef4444', 'error': '#f59e0b'}.get(r.status, '#64748b')
        s_label = {'pass': '✓ 通過', 'fail': '✗ 失敗', 'error': '⚠ 錯誤'}.get(r.status, r.status)
        async_tag = '<span style="background:#ecfdf5;color:#059669;padding:1px 5px;border-radius:3px;font-size:11px">async</span>' if r.use_async else ''

        # DB斷言摘要
        db_summary = ''
        try:
            db_results = json.loads(r.db_assertion_results or '[]')
            if db_results:
                passed = sum(1 for x in db_results if x.get('passed'))
                db_summary = f'<br><span style="font-size:11px;color:#7c3aed">DB斷言: {passed}/{len(db_results)}</span>'
        except Exception:
            pass

        rows_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9">
            <span style="color:{s_color};font-weight:bold">{s_label}</span>
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9">
            {r.method} {async_tag}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;max-width:280px;word-break:break-all">
            <strong>{r.api_name}</strong>
            <br><span style="font-size:11px;color:#64748b">{r.url[:80]}{'...' if len(r.url)>80 else ''}</span>
            {db_summary}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;color:#64748b">
            {r.response_status}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;color:#64748b">
            {r.response_time}ms
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;color:#ef4444;font-size:11px">
            {r.error_message[:60] if r.error_message else ''}
          </td>
        </tr>"""

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;margin:0;padding:20px">
<div style="max-width:860px;margin:0 auto">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);border-radius:12px 12px 0 0;padding:24px 28px;color:#fff">
    <h1 style="margin:0;font-size:20px">{title_icon} API 接口測試報告</h1>
    <p style="margin:6px 0 0;opacity:.85;font-size:14px">{report.name}</p>
  </div>

  <!-- Stats -->
  <div style="background:#fff;padding:20px 28px;display:flex;gap:0">
    <div style="flex:1;text-align:center;padding:12px;border-right:1px solid #f1f5f9">
      <div style="font-size:28px;font-weight:700;color:{status_color}">{pr}%</div>
      <div style="font-size:12px;color:#64748b">通過率</div>
    </div>
    <div style="flex:1;text-align:center;padding:12px;border-right:1px solid #f1f5f9">
      <div style="font-size:28px;font-weight:700">{report.total}</div>
      <div style="font-size:12px;color:#64748b">總數</div>
    </div>
    <div style="flex:1;text-align:center;padding:12px;border-right:1px solid #f1f5f9">
      <div style="font-size:28px;font-weight:700;color:#10b981">{report.passed}</div>
      <div style="font-size:12px;color:#64748b">通過</div>
    </div>
    <div style="flex:1;text-align:center;padding:12px;border-right:1px solid #f1f5f9">
      <div style="font-size:28px;font-weight:700;color:#ef4444">{report.failed}</div>
      <div style="font-size:12px;color:#64748b">失敗</div>
    </div>
    <div style="flex:1;text-align:center;padding:12px;border-right:1px solid #f1f5f9">
      <div style="font-size:28px;font-weight:700;color:#f59e0b">{report.error}</div>
      <div style="font-size:12px;color:#64748b">錯誤</div>
    </div>
    <div style="flex:1;text-align:center;padding:12px">
      <div style="font-size:28px;font-weight:700;color:#64748b">{report.duration}s</div>
      <div style="font-size:12px;color:#64748b">耗時</div>
    </div>
  </div>

  <!-- Progress bar -->
  <div style="background:#fff;padding:0 28px 16px">
    <div style="height:10px;border-radius:5px;overflow:hidden;background:#f1f5f9;display:flex">
      <div style="width:{pr}%;background:#10b981"></div>
      <div style="width:{fr}%;background:#ef4444"></div>
      <div style="width:{er}%;background:#f59e0b"></div>
    </div>
    <div style="font-size:11px;color:#94a3b8;margin-top:4px">
      執行時間: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}
    </div>
  </div>

  <!-- Detail Table -->
  <div style="background:#fff;border-top:2px solid #f1f5f9">
    <div style="padding:12px 28px;font-weight:600;font-size:14px;color:#374151;border-bottom:2px solid #f1f5f9">
      接口執行明細
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="background:#f8fafc">
          <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0">狀態</th>
          <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0">方法</th>
          <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0">接口</th>
          <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0">HTTP</th>
          <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0">耗時</th>
          <th style="padding:10px 12px;text-align:left;color:#475569;font-weight:600;border-bottom:2px solid #e2e8f0">錯誤</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="background:#1e1b4b;border-radius:0 0 12px 12px;padding:14px 28px;color:#a5b4fc;font-size:12px;text-align:center">
    API 接口測試平台 · 自動生成報告 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  </div>

</div>
</body>
</html>"""
    return html


# ─────────────────────────────────────────────
#  發送報告郵件
# ─────────────────────────────────────────────

def send_report_email(report, to_list: list, config=None) -> tuple:
    """
    發送測試報告郵件。
    report: TestReport 對象
    to_list: 收件人列表
    config: EmailConfig（None 則自動取激活配置）
    返回 (success, message)
    """
    if config is None:
        config, err = get_active_email_config()
        if err:
            return False, err

    pr = report.pass_rate
    icon = '✅' if pr == 100 else ('⚠️' if pr >= 60 else '❌')
    subject = f'{icon} 測試報告 | {report.name} | 通過率 {pr}% ({report.passed}/{report.total})'
    html = build_report_html(report)
    return _send_mail(config, to_list, subject, html)


# ─────────────────────────────────────────────
#  底層發送
# ─────────────────────────────────────────────

def _send_mail(config, to_list: list, subject: str, html: str) -> tuple:
    """底層郵件發送"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = formataddr((config.from_name, config.from_addr))
        msg['To']      = ', '.join(to_list)
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        if config.use_ssl:
            smtp = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=15)
        else:
            smtp = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15)
            if config.use_tls:
                smtp.starttls()

        smtp.login(config.username, config.password)
        smtp.sendmail(config.from_addr, to_list, msg.as_string())
        smtp.quit()

        logger.info(f'郵件發送成功: {subject} → {to_list}')
        return True, f'郵件已發送給 {", ".join(to_list)}'
    except Exception as e:
        logger.error(f'郵件發送失敗: {e}')
        return False, f'郵件發送失敗: {str(e)}'
