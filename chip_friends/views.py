from __future__ import division, unicode_literals
import calendar
import datetime
import math

from flask import abort, redirect, render_template, request, url_for
from flask_login import current_user
from flask_security import login_required
from peewee import fn, JOIN, SQL

from .app import app
from .forms import UsageForm, QRCodeForm
from .models import User, QRCode, QRUse


@app.route('/')
def index():
    if current_user.is_authenticated:
        me = User(**current_user._data)
        my_uses = me.qruse_set.order_by(QRUse.when.desc())
    else:
        my_uses = None
    qrs = QRCode.select().order_by(QRCode.registrant)
    # TODO: sort QRs by total uses...
    return render_template('index.html', my_uses=my_uses, qrs=qrs)


@app.route('/about/')
def about():
    return render_template('about.html')


@app.route('/use/', methods=['POST'])
@login_required
def pick_barcode():
    me = User(**current_user._data)

    today = datetime.date.today()
    begin = datetime.datetime.combine(today, datetime.time.min)
    end = datetime.datetime.combine(today, datetime.time.max)
    total_days = calendar.monthrange(today.year, today.month)[1]
    target = min(int(math.ceil(11 * today.day / total_days)) + 1, 11)

    uses_today = (QRUse.select()
                       .where(QRUse.when >= begin)
                       .where(QRUse.when <= end)
                       .where(QRUse.confirmed | (QRUse.confirmed >> None)))
    q = (QRCode
        .select(QRCode, fn.Count(QRUse.id).alias('count'))
        .join(QRUse, JOIN.LEFT_OUTER)
        .group_by(QRCode.id)
        .order_by(SQL('count').desc()))
    used_today = list(QRCode.select().join(QRUse).where(QRUse.id << uses_today))
    if used_today:  # SQL breaks on empty IN queries...
        q = q.where(QRCode.id.not_in(used_today))

    # could *almost* do this in SQL, but it's hard, so don't.
    max_below = None
    min_above = None
    for qr in q:
        if qr.id is None or qr.count >= 11:
            pass
        elif qr.count < target:
            if max_below is None or qr.count > max_below.count:
                max_below = qr
        else:
            if min_above is None or qr.count < min_above.count:
                min_above = qr

    if max_below is not None:
        qr = max_below
    elif min_above is not None:
        qr = min_above
    else:
        return render_template('no_codes.html', uses_today=uses_today)

    qr_use = QRUse(user=me, qr_code=qr, when=datetime.datetime.now(),
                   confirmed=None)
    qr_use.save()
    return redirect(url_for('use', use_id=qr_use.id))


@app.route('/use/<int:use_id>/')
@login_required
def use(use_id):
    try:
        use = QRUse.get(QRUse.id == use_id)
    except QRUse.DoesNotExist:
        return abort(404)
    return render_template('use.html', use=use)


@app.route('/use/confirm/<int:use_id>/<int:redeemed_free>/', methods=['POST'])
@login_required
def use_confirm(use_id, redeemed_free):
    try:
        use = QRUse.get(QRUse.id == use_id)
    except QRUse.DoesNotExist:
        return abort(404)
    use.confirmed = True
    use.redeemed_free = bool(redeemed_free)
    use.save()
    return render_template('confirm.html', use=use)


@app.route('/use/confirmed/<int:use_id>/<int:redeemed_free>/')
@login_required
def use_confirmed(use_id, redeemed_free):
    try:
        use = QRUse.get(QRUse.id == use_id)
    except QRUse.DoesNotExist:
        return abort(404)
    return render_template('confirm.html', use=use)


@app.route('/use/cancel/<int:use_id>/', methods=['POST'])
@login_required
def use_cancel(use_id):
    try:
        use = QRUse.get(QRUse.id == use_id)
    except QRUse.DoesNotExist:
        return abort(404)
    use.delete_instance()
    return render_template('cancel.html', use=use)


@app.route('/use-specific/<int:qr_id>/', methods=['GET', 'POST'])
@login_required
def use_specific(qr_id):
    me = User(**current_user._data)
    try:
        qr = QRCode.get(QRCode.id == qr_id)
    except QRCode.DoesNotExist:
        return abort(404)

    use = QRUse(qr_code=qr, user=me)

    form = UsageForm(
        request.form,
        data={'when': use.when,
              'redeemed_free': 'true' if use.redeemed_free else 'false'})
    form.qr_code = qr
    form.qr_use = use

    if form.validate_on_submit():
        use.confirmed = True
        use.redeemed_free = form.redeemed_free.data == 'true'
        use.when = form.when.data
        if isinstance(use.when, datetime.date):
            use.when = datetime.datetime.combine(use.when, datetime.time(0, 0, 1))
        use.save()
        return redirect(url_for(
            'use_confirmed', use_id=use.id, redeemed_free=use.redeemed_free))
    return render_template('use-specific.html', use=use, form=form)


@app.route('/new-card/', methods=['GET', 'POST'])
@login_required
def new_card():
    form = QRCodeForm(request.form)
    if form.validate_on_submit():
        qr_code = QRCode()
        form.populate_obj(qr_code)
        s = qr_code.barcode.find('?barcode=')
        if s != -1:
            qr_code.barcode = qr_code.barcode[s + len('?barcode='):]
        qr_code.save()
        return redirect(url_for('index'))
    return render_template('new-card.html', form=form)
