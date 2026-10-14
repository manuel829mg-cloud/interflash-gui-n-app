"""Private PDF invoices and transactional notifications for new invoices."""
from io import BytesIO
from pathlib import Path
from datetime import date
from html import escape
import base64
import re


def render_pdf(inv, company, banks=(), logo_path=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import reportlab
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    styles = getSampleStyleSheet()
    font_dir = Path(reportlab.__file__).resolve().parent / 'fonts'
    for name, filename in [('Invoice','Vera.ttf'),('InvoiceBold','VeraBd.ttf'),('InvoiceItalic','VeraIt.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name,str(font_dir / filename)))
    for style in styles.byName.values():
        style.fontName = 'InvoiceBold' if 'Heading' in style.name or style.name=='Title' else 'Invoice'
    styles['Normal'].fontSize = 13
    styles['Normal'].leading = 18
    def p(value, style='Normal'):
        return Paragraph(escape(str(value or '')).replace('\n', '<br/>'), styles[style])
    def day(value):
        try: return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
        except ValueError: return str(value or '-')
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(420, 760), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
    story = []
    brand = [p(company.get('business_name') or 'INTER Flash', 'Heading1')]
    for key in ('business_address', 'business_phone', 'business_email', 'business_rnc'):
        if company.get(key): brand.append(p(company[key]))
    logo_path = logo_path or Path(__file__).resolve().parent / 'static' / 'interflash-symbol.png'
    if Path(logo_path).is_file():
        header = Table([[Image(str(logo_path), width=64, height=64), brand]], colWidths=[76,296])
        header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
        story.append(header)
    else:
        story.extend(brand)
    story += [Spacer(1,16), p('FACTURA IF-%06d' % int(inv['id']), 'Heading1')]
    status = inv.get('status') or 'PENDIENTE'
    story.append(p('Estado: ' + status))
    story += [Spacer(1,16), p('FACTURADO A', 'Heading3'), p(inv['customer'], 'Heading2')]
    for value in (inv.get('customer_code'), inv.get('phone'), inv.get('address')):
        if value: story.append(p(value))
    story += [Spacer(1,16)]
    dates = Table([[p('Emisión: '+day(inv.get('issue_date'))), p('Vencimiento: '+day(inv.get('due_date')))],
                   [p('Período: '+str(inv.get('period') or '-')), p('Modalidad: POSPAGO')]], colWidths=[186,186])
    dates.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    story += [dates, Spacer(1,12)]
    description = str(inv.get('concept') or 'Servicio de Internet')
    if inv.get('plan_name'): description += '\nPlan: '+str(inv['plan_name'])
    if inv.get('plan_speed'): description += '\nVelocidad: '+str(inv['plan_speed'])
    amount = float(inv.get('amount') or 0)
    paid = float(inv.get('paid_total') or 0)
    balance = max(0,amount-paid) if status != 'ANULADA' else 0
    table = Table([[p('CONCEPTO'),p('IMPORTE')],[p(description),p('RD$%s' % format(amount,',.2f'))]], colWidths=[232,140])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8f1fc')),('LINEBELOW',(0,0),(-1,0),1,colors.HexColor('#1968c7')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),12)]))
    story += [table,Spacer(1,12)]
    totals = Table([[p('Total facturado'),p('RD$'+format(amount,',.2f'))],[p('Pagos registrados'),p('RD$'+format(paid,',.2f'))],[p('BALANCE PENDIENTE','Heading3'),p('RD$'+format(balance,',.2f'),'Heading3')]],colWidths=[232,140])
    story += [totals,Spacer(1,16)]
    if banks:
        story.append(p('CUENTAS PARA PAGAR','Heading3'))
        for bank in banks:
            story.append(p(' · '.join(str(bank.get(k) or '') for k in ('bank','account_type','account_number','label') if bank.get(k))))
        story.append(p('Incluye tu referencia de cliente al enviar el comprobante.'))
    story += [Spacer(1,16),p(company.get('billing_footer') or 'Gracias por preferir INTER Flash.')]
    doc.build(story)
    return output.getvalue()


def invoice_data(c, invoice_id):
    row = c.execute('''SELECT i.*,cu.name customer,cu.code customer_code,cu.phone,cu.address,cu.status customer_status,
        COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id=i.id),0) paid_total
        FROM invoices i JOIN customers cu ON cu.id=i.customer_id WHERE i.id=?''',(invoice_id,)).fetchone()
    if not row: raise ValueError('Factura no encontrada.')
    company = dict(c.execute('SELECT key,value FROM app_settings'))
    banks = [dict(r) for r in c.execute('SELECT * FROM bank_accounts WHERE active=1 ORDER BY bank')]
    return dict(row),company,banks


def send_invoice(c, phone, invoice_id, caption=None):
    import whatsapp_suite as wa
    import waha_suite as waha
    try:
        inv,company,banks = invoice_data(c,int(invoice_id))
        if inv['status']!='PAGADA' or inv['customer_status']=='ELIMINADO':
            raise ValueError('Factura anulada o cliente eliminado; no se envió el documento.')
        if wa._wa_phone(inv['phone']) != wa._wa_phone(phone):
            raise ValueError('El teléfono del cliente cambió; revisa el destinatario antes de reenviar.')
        if not waha.enabled(): raise ValueError('El envío de factura PDF requiere el proveedor WAHA conectado.')
        if not re.fullmatch(r'[1-9][0-9]{7,14}',wa._wa_phone(phone)):
            raise ValueError('Número de teléfono inválido.')
        if float(inv['paid_total']) < float(inv['amount']):
            raise ValueError('La factura todavía tiene balance pendiente; no se envió como pagada.')
        cfg = waha.config()
        filename = 'Factura-IF-%06d.pdf' % inv['id']
        pdf = render_pdf(inv,company,banks)
        result = waha.api('/api/sendFile',{
            'session':cfg['session_name'],'chatId':wa._wa_phone(phone)+'@c.us',
            'file':{'mimetype':'application/pdf','filename':filename,'data':base64.b64encode(pdf).decode('ascii')},
            'caption':caption or 'Hola '+inv['customer']+', adjuntamos tu factura '+('IF-%06d' % inv['id'])+' de INTER Flash.'},cfg)
        mid = result.get('id')
        if isinstance(mid,dict): mid=mid.get('_serialized')
        if not isinstance(mid,str) or not mid:
            raise ValueError('No se confirmó el PDF. Revisa el chat antes de reintentar para evitar duplicados.')
        return True,'waha:'+cfg['session_name']+':'+mid,''
    except (ValueError,OSError,waha.APIError) as exc:
        return False,'',str(exc)


def setup(app):
    import app as base
    c=base.db()
    try:
        c.execute('DROP TRIGGER IF EXISTS whatsapp_new_invoice_pdf')
        c.execute("""UPDATE whatsapp_outbox SET status='CANCELADO',error='Aviso previo al pago desactivado; la factura se envía al pagar'
            WHERE status='PENDIENTE' AND (template_code='INVOICE' OR template_code='ZONE_REMINDER' OR template_code LIKE 'INVOICE_PDF:%' OR template_code LIKE 'INVOICE_PDF_DUE:%')""")
        c.commit()
    finally: c.close()
