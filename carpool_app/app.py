import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import calendar
from whitenoise import WhiteNoise

# --- Flaskアプリケーションの初期化 ---
# 静的ファイルの設定は、WhiteNoiseに完全に一任するため、ここではシンプルに初期化
app = Flask(__name__)

# --- WhiteNoiseの設定 ---
# Render公式ドキュメントで推奨されている、最も確実で強力な設定
# root: ファイルシステム上の静的フォルダの場所を 'static/' と明示
# prefix: ブラウザがアクセスする際のURLの接頭辞を 'static/' と明示
app.wsgi_app = WhiteNoise(app.wsgi_app, root="static/", prefix="static/")

# --- データベース設定 ---
# ベースディレクトリの絶対パスを取得
basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # RenderのPostgreSQL URLは 'postgres://' で始まるが、SQLAlchemyは 'postgresql://' を要求するため置換
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url.replace("postgres://", "postgresql://")
else:
    # ローカル開発用のSQLite設定
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'carpool.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_super_secret_key'

db = SQLAlchemy(app)

# --- モデル定義 (変更なし) ---
class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    departure_point = db.Column(db.String(50), nullable=False, default='京大発')
    slot_time = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, default=4)
    reservations = db.relationship('Reservation', backref='slot', lazy=True, cascade="all, delete-orphan")

    @property
    def available_slots(self):
        return self.capacity - len(self.reservations)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('slot.id'), nullable=False)

# --- ルート定義 (変更なし) ---
@app.route('/')
def index():
    today = datetime.utcnow().date()
    year = request.args.get('year', default=today.year, type=int)
    month = request.args.get('month', default=today.month, type=int)

    first_day_of_month = datetime(year, month, 1)
    if month == 12:
        last_day_of_month = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day_of_month = datetime(year, month + 1, 1) - timedelta(days=1)

    slots = Slot.query.filter(
        Slot.slot_time >= datetime.combine(first_day_of_month.date(), datetime.min.time()),
        Slot.slot_time <= datetime.combine(last_day_of_month.date(), datetime.max.time())
    ).order_by(Slot.slot_time).all()

    cal = calendar.Calendar()
    month_days = cal.monthdatescalendar(year, month)

    prev_month = first_day_of_month - timedelta(days=1)
    next_month = last_day_of_month + timedelta(days=1)
    list_slots = Slot.query.filter(Slot.slot_time >= datetime.utcnow()).order_by(Slot.slot_time).all()

    return render_template('index.html',
                           month_days=month_days,
                           slots=slots,
                           year=year,
                           month=month,
                           prev_year=prev_month.year,
                           prev_month=prev_month.month,
                           next_year=next_month.year,
                           next_month=next_month.month,
                           today=today,
                           list_slots=list_slots)


@app.route('/reserve', methods=['POST'])
def reserve():
    user_name = request.form.get('user_name')
    slot_id = request.form.get('slot_id')
    if not user_name:
        flash('名前を入力してください。', 'error')
        return redirect(url_for('index'))
    slot_to_reserve = Slot.query.get(slot_id)
    if slot_to_reserve and slot_to_reserve.available_slots > 0:
        reservation = Reservation(user_name=user_name, slot_id=slot_id)
        db.session.add(reservation)
        db.session.commit()
        flash(f'{slot_to_reserve.slot_time.strftime("%m月%d日 %H:%M")}の予約が完了しました。', 'success')
    else:
        flash('満席か、予約枠が見つかりませんでした。', 'error')
    return redirect(url_for('index'))

@app.route('/my_reservations', methods=['GET', 'POST'])
def my_reservations():
    reservations = []
    searched_name = ""
    if request.method == 'POST':
        user_name = request.form.get('user_name')
        if user_name:
            searched_name = user_name
            reservations = Reservation.query.filter(Reservation.user_name.ilike(f'%{user_name}%')).all()
            if not reservations:
                flash('その名前の予約は見つかりませんでした。', 'info')
        else:
            flash('名前を入力してください。', 'error')
    return render_template('my_reservations.html', reservations=reservations, searched_name=searched_name)

@app.route('/cancel_reservation/<int:reservation_id>', methods=['POST'])
def cancel_reservation(reservation_id):
    reservation_to_delete = Reservation.query.get_or_404(reservation_id)
    user_name = reservation_to_delete.user_name
    slot_time_str = reservation_to_delete.slot.slot_time.strftime('%Y-%m-%d %H:%M')
    try:
        db.session.delete(reservation_to_delete)
        db.session.commit()
        flash(f'{user_name}さんの {slot_time_str} の予約をキャンセルしました。', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'キャンセル処理中にエラーが発生しました: {e}', 'error')
    return redirect(url_for('my_reservations'))

@app.route('/admin')
def admin():
    today = datetime.utcnow().date()
    slots = Slot.query.filter(Slot.slot_time >= datetime.combine(today, datetime.min.time())).order_by(Slot.slot_time).all()
    return render_template('admin.html', slots=slots)

@app.route('/add_slot', methods=['POST'])
def add_slot():
    slot_time_str = request.form.get('slot_time')
    departure_point = request.form.get('departure_point')
    if slot_time_str:
        slot_time = datetime.strptime(slot_time_str, '%Y-%m-%dT%H:%M')
        new_slot = Slot(slot_time=slot_time, departure_point=departure_point)
        db.session.add(new_slot)
        db.session.commit()
        flash('新しい送迎枠が追加されました。', 'success')
    else:
        flash('日時が選択されていません。', 'error')
    return redirect(url_for('admin'))

@app.route('/delete_slot/<int:slot_id>', methods=['POST'])
def delete_slot(slot_id):
    slot_to_delete = Slot.query.get_or_404(slot_id)
    db.session.delete(slot_to_delete)
    db.session.commit()
    flash('送迎枠が削除されました。', 'success')
    return redirect(url_for('admin'))

def create_tables():
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5001)
