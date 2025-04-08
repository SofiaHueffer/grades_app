from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Length
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
from flask_mail import Mail, Message

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')

conn = psycopg2.connect(
    dbname=os.environ.get('DB_NAME'),
    user=os.environ.get('DB_USER'),
    password=os.environ.get('DB_PASSWORD'),
    host=os.environ.get('DB_HOST'),
    port=os.environ.get('DB_PORT')
)

cur = conn.cursor()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user:
        return User(user[0], user[1])
    return None

class SignupForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField('Password', validators=[DataRequired()])
    cur.execute("SELECT DISTINCT dates FROM overview_details ORDER BY dates;")
    dates = cur.fetchall()
    year = SelectField('Year', choices=[(str(oy[0]), str(oy[0])) for oy in dates], validators=[DataRequired()])
    submit = SubmitField('Sign Up')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        username = form.username.data
        password = generate_password_hash(form.password.data)
        year = form.year.data

        try:
            cur.execute("INSERT INTO users (username, password, Year) VALUES (%s, %s, %s) RETURNING id", (username, password, year))
            user_id = cur.fetchone()[0]
            conn.commit()
            login_user(User(user_id, username))
            flash("Account created successfully", "success")
            reset_tables()
            return redirect(url_for('electives'))
        except psycopg2.IntegrityError:
            conn.rollback()
            flash("Username already exists. Choose another one.", "danger")

    return render_template('signup.html', form=form)

class ElectivesForm(FlaskForm):
    elec_1 = SelectField('First Elective', validators=[DataRequired()])
    elec_2 = SelectField('Second Elective', validators=[DataRequired()])
    elec_3 = SelectField('Third Elective', validators=[DataRequired()])
    elec_4 = SelectField('Fourth Elective', validators=[DataRequired()])
    elec_5 = SelectField('Fifth Elective', validators=[DataRequired()])
    submit = SubmitField('Submit')

    def __init__(self, electives, *args, **kwargs):
        super(ElectivesForm, self).__init__(*args, **kwargs)
        self.elec_1.choices = [(e, e) for e in electives]
        self.elec_2.choices = [(e, e) for e in electives]
        self.elec_3.choices = [(e, e) for e in electives]
        self.elec_4.choices = [(e, e) for e in electives]
        self.elec_5.choices = [(e, e) for e in electives]

@app.route('/electives', methods=['GET', 'POST'])
@login_required
def electives():
    user_id = current_user.id
    cur.execute(f"""WITH user_year as (select Year from users where id = %s) 
        select DISTINCT Module FROM Electives where Year = (SELECT Year FROM user_year) order by Module""", (user_id,))
    electives = [row[0] for row in cur.fetchall()]

    if not electives: 
        return redirect(url_for('index')) 

    form = ElectivesForm(electives=electives)

    if form.validate_on_submit():
        if 'skip' in request.form:
            session['selected_electives'] = []
        else:
            selected_electives = [form.elec_1.data, form.elec_2.data, form.elec_3.data, form.elec_4.data, form.elec_5.data]
            session['selected_electives'] = selected_electives

        add_electives()

        return redirect(url_for('index'))  
    return render_template('electives.html', form=form)

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    flash(" ")
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        cur.execute("SELECT id, password FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

        if user and check_password_hash(user[1], password):
            login_user(User(user[0], username))
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged Out')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user_id = current_user.id
    cur.execute(f"select username, Year from users where id = %s", (user_id,))
    user_data = cur.fetchone()
    username = user_data[0]
    user_year = user_data[1]

    def replace_none_with_blank(rows):
        return [[cell if cell is not None else "" for cell in row] for row in rows]

    cur.execute("SELECT Year, Weighting, Current_Score, Current_Grade FROM Overview WHERE UserID = %s AND Current_Score is not null ORDER BY Year;", (user_id,))
    rows = replace_none_with_blank(cur.fetchall())

    value = max(len(rows) - 1, 1)

    table_name = f"Year_{value}"
    query = f"""
        SELECT Module, Credits, Current_Score, Current_Grade
        FROM {table_name}
        WHERE UserID = %s AND Current_Score != Total_Score
        ORDER BY Module;
    """
    cur.execute(query, (user_id,))

    curr_year = replace_none_with_blank(cur.fetchall())

    total_hours, total_week_hours, badge, streak = studyinfo(user_id, cur)

    cur.execute("SELECT Task, Notes, Due_Date FROM Tasks WHERE UserID = %s", (user_id,))
    task_list = cur.fetchall()

    cur.execute("""SELECT module, days_left
                   FROM Deadlines WHERE Year = %s AND days_left >= 0 AND days_left <= 5 order by date""", (user_year,))
    deadlines = cur.fetchall() or []

    return render_template("index.html", Overview=rows, value=value, Curr_Year=curr_year, 
        username=username, user_year=user_year,  
        badge=badge, streak=streak, task_list=task_list, 
        deadlines=deadlines, user_value=value)

@app.route('/grades')
@login_required
def grades():
    user_id = current_user.id
    cur.execute(f"select username, Year from users where id = %s", (user_id,))
    user_data = cur.fetchone()
    username = user_data[0]
    user_year = user_data[1]

    def replace_none_with_blank(rows):
        return [[cell if cell is not None else "" for cell in row] for row in rows]

    cur.execute("SELECT Year, Weighting, Current_Score, Current_Grade, Total_Score, Total_Grade FROM Overview WHERE UserID = %s ORDER BY Year;", (user_id,))
    rows = replace_none_with_blank(cur.fetchall())

    cur.execute("SELECT Module, Credits, Weight_1, Score_1, Grade_1, Weight_2, Score_2, Grade_2, Weight_3, Score_3, Grade_3, Weight_4, Score_4, Grade_4, Current_Score, Current_Grade, Total_Score, Total_Grade, min_score FROM Year_1 WHERE UserID = %s ORDER BY Module;", (user_id,))
    one = replace_none_with_blank(cur.fetchall())

    cur.execute("SELECT Module, Credits, Weight_1, Score_1, Grade_1, Weight_2, Score_2, Grade_2, Weight_3, Score_3, Grade_3, Weight_4, Score_4, Grade_4, Current_Score, Current_Grade, Total_Score, Total_Grade, min_score FROM Year_2 WHERE UserID = %s ORDER BY Module;", (user_id,))
    two = replace_none_with_blank(cur.fetchall())

    cur.execute("SELECT Module, Credits, Weight_1, Score_1, Grade_1, Weight_2, Score_2, Grade_2, Weight_3, Score_3, Grade_3, Weight_4, Score_4, Grade_4, Current_Score, Current_Grade, Total_Score, Total_Grade, min_score FROM Year_3 WHERE UserID = %s ORDER BY Module;", (user_id,))
    three = replace_none_with_blank(cur.fetchall())

    return render_template("grades.html", Overview=rows, row_count=len(rows), 
        Year_1=one, one_count=len(one), Year_2=two, two_count=len(two), 
        Year_3=three, three_count=len(three), username=username, user_year=user_year)

@app.route('/reset', methods=['POST'])
def reset_tables():
    user_id = current_user.id
    cur.execute(f"select Year from users where id = %s", (user_id,))
    user_year = cur.fetchall()[0]

    cur.execute("DELETE FROM Overview WHERE UserID = %s;", (user_id,))
    cur.execute(f"SELECT Overall, Weighting FROM Overview_details where Dates = %s", (user_year))
    overview_details = cur.fetchall()
    insert_query = """
        INSERT INTO Overview (UserID, Year, Weighting, Current_Score, Current_Grade, Total_Score, Total_Grade) 
        VALUES (%s, %s, %s, NULL, NULL, NULL, NULL)
    """
    for year, weighting in overview_details:
        cur.execute(insert_query, (user_id, year, weighting))

    year_tables = {
        "Year_1_Modules": "Year_1",
        "Year_2_Modules": "Year_2",
        "Year_3_Modules": "Year_3"
    }

    for module_table, year_table in year_tables.items():
        cur.execute(f"DELETE FROM {year_table} WHERE UserID = %s;", (user_id,))
        cur.execute(f"SELECT Module, Credit, Weight_1, Weight_2, Weight_3, Weight_4 FROM {module_table} where Year = %s", (user_year))
        modules = cur.fetchall()

        insert_query = f"""
            INSERT INTO {year_table} (
                UserID, Module, Credits, Weight_1, Score_1, Grade_1, 
                Weight_2, Score_2, Grade_2, Weight_3, Score_3, Grade_3, 
                Weight_4, Score_4, Grade_4, Current_Score, Current_Grade, 
                Total_Score, Total_Grade, min_score
            ) VALUES (%s, %s, %s, %s, NULL, NULL, %s, NULL, NULL, %s, NULL, NULL, %s, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
        """

        for module in modules:
            cur.execute(insert_query, (user_id, *module))
    conn.commit()
    return redirect(url_for('index'))

@app.route('/add_electives', methods=['POST'])
def add_electives():
    user_id = current_user.id
    cur.execute(f"select Year from users where id = %s", (user_id,))
    user_year = cur.fetchall()[0]

    selected_electives = session.get('selected_electives', [])
    if selected_electives:
        cur.execute("DELETE FROM Year_3 WHERE UserID = %s;", (user_id,))
        cur.execute(f"SELECT Module, Credit, Weight_1, Weight_2, Weight_3, Weight_4 FROM Year_3_Modules where Year = %s", (user_year))
        year_3_modules = cur.fetchall()

        query = """
            SELECT Module, Credit, Weight_1, Weight_2, Weight_3, Weight_4 
            FROM Electives 
            WHERE Module IN %s
        """
        cur.execute(query, (tuple(selected_electives),))
        elective_modules = cur.fetchall()

        modules = year_3_modules + elective_modules  

        insert_query = """
            INSERT INTO Year_3 (
                UserID, Module, Credits, Weight_1, Score_1, Grade_1, 
                Weight_2, Score_2, Grade_2, Weight_3, Score_3, Grade_3, 
                Weight_4, Score_4, Grade_4, Current_Score, Current_Grade, 
                Total_Score, Total_Grade, min_score
            ) VALUES (%s, %s, %s, %s, NULL, NULL, %s, NULL, NULL, %s, NULL, NULL, %s, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
        """
        for module in modules:
            cur.execute(insert_query, (user_id, *module))

    conn.commit()
    return redirect(url_for('index'))

@app.route('/wipe', methods=['Post'])
def wipe():
    cur.execute("""TRUNCATE TABLE Overview RESTART IDENTITY CASCADE;
    TRUNCATE TABLE Year_1 RESTART IDENTITY CASCADE;
    TRUNCATE TABLE Year_2 RESTART IDENTITY CASCADE;
    TRUNCATE TABLE Year_3 RESTART IDENTITY CASCADE;
    TRUNCATE TABLE Users RESTART IDENTITY CASCADE;""")
    conn.commit()
    return redirect(url_for('index'))

def grade_name(inp):
    if inp is None:
        out = None
    elif inp >= 70:
        out = "First"
    elif inp >= 60:
        out = "2.1"
    elif inp >= 50:
        out = "2.2"
    elif inp >= 40:
        out = "3rd"
    else:
        out = "Fail"
    return out

@app.route('/update', methods=['GET', 'POST'])
@login_required
def update_scores():
    user_id = current_user.id
    cur.execute("SELECT DISTINCT Year FROM Overview WHERE Year != 'Overall' ORDER BY Year;")
    years = cur.fetchall()

    modules_by_year = {}
    year_tables = {'Year 1': 'Year_1', 'Year 2': 'Year_2', 'Year 3': 'Year_3'} 
    for year, table in year_tables.items():
        cur.execute(f"""SELECT Module FROM {table} WHERE UserID = %s ORDER BY Module;""", (user_id,))
        modules_by_year[year] = cur.fetchall()
    module_to_year = {module[0]: year for year, modules in modules_by_year.items() for module in modules}
    

    if request.method == 'POST':
        module = request.form['module']
        score_type = request.form['score_type'] 
        action = request.form['action']

        year = module_to_year.get(module)
        table_name = f"Year_{year[-1]}"
        index = score_type.split("_")[-1]

        #change grade
        if action == 'update':
            score = float(request.form['new_score'])
            flash("Score updated successfully", "success")

            grade = grade_name(score)
            cur.execute(f"""UPDATE {table_name}
                            SET {score_type} = %s, Grade_{index} = %s
                            WHERE Module = %s and UserID = %s""", (score, grade, module, user_id,))
        
        elif action == 'reset':
            cur.execute(f"""UPDATE {table_name}
                            SET {score_type} = NULL, Grade_{index} = NULL
                            WHERE Module = %s and UserID = %s""", (module, user_id,))


        #update module score
        cur.execute(f"""SELECT weight_1, score_1, weight_2, score_2, 
                               weight_3, score_3, weight_4, score_4 
                        FROM {table_name} WHERE Module = %s and UserID = %s""", (module, user_id,))
        result = cur.fetchone()
        
        if result:
            weight_1, score_1, weight_2, score_2, weight_3, score_3, weight_4, score_4 = [0 if v is None else v for v in result]

            current_score = ((weight_1 * score_1) + (weight_2 * score_2) + (weight_3 * score_3) + (weight_4 * score_4)) / ((
                (weight_1 if score_1 > 0 else 0) + 
                (weight_2 if score_2 > 0 else 0) + 
                (weight_3 if score_3 > 0 else 0) + 
                (weight_4 if score_4 > 0 else 0)
            ) if (score_1 + score_2 + score_3 + score_4) > 0 else 1)
            current_score = round(current_score, 2) if current_score > 0 else None
            current_grade = grade_name(current_score)
            
            cur.execute(f"""UPDATE {table_name}
                            SET Current_Score = %s, Current_Grade = %s
                            WHERE Module = %s and UserID = %s""", (current_score, current_grade, module, user_id,))
            total_score = (weight_1 * score_1) + (weight_2 * score_2) + (weight_3 * score_3) + (weight_4 * score_4)
            total_score = round(total_score/100, 2) if total_score > 0 else None

            if total_score == current_score:
                total_grade = grade_name(total_score)
            else:
                total_grade = "-"
            
            cur.execute(f"""UPDATE {table_name}
                            SET Total_Score = %s, Total_Grade = %s
                            WHERE Module = %s and UserID = %s""", (total_score, total_grade, module, user_id))

        #update year score
        cur.execute(f"""SELECT sum(COALESCE(Credits, 0) * COALESCE(Total_Score, 0))/
            nullif(sum(COALESCE(Credits, 0) * COALESCE(Total_Score, 0) * 1/NULLIF(Current_Score, 0)),0) FROM {table_name} WHERE UserID = %s""", (user_id,))
        year_current_score = cur.fetchone()[0]
        year_current_score = round(year_current_score, 2) if year_current_score is not None else None
        year_current_grade = grade_name(year_current_score)

        cur.execute(f"""UPDATE Overview
                            SET Current_Score = %s, Current_Grade = %s
                            WHERE Year = %s and UserID = %s""", (year_current_score, year_current_grade, year, user_id,))

        cur.execute(f"""SELECT SUM(COALESCE(Credits, 0) * COALESCE(Total_Score, 0))/sum(COALESCE(Credits, 0)) FROM {table_name} WHERE UserID = %s""", (user_id,))
        year_total_score = cur.fetchone()[0]
        year_total_score = round(year_total_score, 2) if year_total_score > 0 else None

        if year_total_score == year_current_score:
            year_total_grade = grade_name(year_total_score)
        else:
            year_total_grade = "-"

        cur.execute(f"""UPDATE Overview
                            SET Total_Score = %s, Total_Grade = %s
                            WHERE Year = %s and UserID = %s""", (year_total_score, year_total_grade, year, user_id,))
        
        #update degree score
        cur.execute(f"""SELECT sum(COALESCE(Weighting, 0) * COALESCE(Total_Score, 0))/
            nullif(sum(COALESCE(Weighting, 0) * COALESCE(Total_Score, 0) * 1/NULLIF(Current_Score, 0)),0) FROM Overview
            WHERE Year != 'Overall' and UserID = %s""", (user_id,))
        degree_current_score = cur.fetchone()[0]
        degree_current_score = round(degree_current_score, 2) if degree_current_score is not None else None
        degree_current_grade = grade_name(degree_current_score)

        cur.execute(f"""UPDATE Overview
                            SET Current_Score = %s, Current_Grade = %s
                            WHERE Year = 'Overall' and UserID = %s""", (degree_current_score, degree_current_grade, user_id,))

        cur.execute(f"""SELECT SUM(Weighting * COALESCE(Total_Score, 0)) FROM Overview where Year != 'Overall' and UserID = %s""", (user_id,))
        degree_total_score = cur.fetchone()[0]/100
        degree_total_score = round(degree_total_score, 2) if degree_total_score > 0 else None

        if degree_total_score == degree_current_score:
            degree_total_grade = grade_name(degree_total_score)
        else: 
            degree_total_grade = "-"

        cur.execute(f"""UPDATE Overview
                            SET Total_Score = %s, Total_Grade = %s
                            WHERE Year = 'Overall' and UserID = %s""", (degree_total_score, degree_total_grade, user_id,))

        conn.commit()

        return redirect(url_for('update_scores'))

    return render_template("update.html", years=years, modules_by_year=modules_by_year)

@app.route('/minscore/<year>', methods=['GET', 'POST'])
@login_required
def min_score(year):
    user_id = current_user.id
    target_score = request.form['target_score']

    flash(f"Target Set to {target_score}", "success")

    table_name = f"Year_{year}"
    cur.execute(f"""
        UPDATE {table_name}
        SET min_score = ((%s - COALESCE(find_weight.Total_Score)) / last_weight)*100
        FROM (
            SELECT UserID, module, Total_Score,
                CASE 
                    WHEN score_4 IS NULL AND weight_4 IS NOT NULL THEN weight_4
                    WHEN score_3 IS NULL AND weight_3 IS NOT NULL THEN weight_3
                    WHEN score_2 IS NULL AND weight_2 IS NOT NULL THEN weight_2
                    WHEN score_1 IS NULL AND weight_1 IS NOT NULL THEN weight_1
                END AS last_weight
            FROM {table_name}
        ) AS find_weight
        WHERE {table_name}.module = find_weight.module AND {table_name}.UserID = find_weight.UserID;
    """, (target_score,))

    conn.commit()
    return redirect(url_for('grades'))

@app.route('/deadlines', methods=['GET', 'POST'])
@login_required
def deadlines():
    user_id = current_user.id
    cur.execute(f"select Year from users where id = %s", (user_id,))
    user_year = cur.fetchone()[0] 

    cur.execute("""UPDATE Deadlines SET days_left = Date - CURRENT_DATE""")
    conn.commit()

    cur.execute("SELECT DISTINCT module FROM Deadlines WHERE Year = %s", (user_year,))
    all_modules = [row[0] for row in cur.fetchall()]

    colours = ["#FFADAD", "#FFD6A5", "#FDFFB6", "#CAFFBF", "#9BF6FF", 
        "#A0C4FF", "#BDB2FF", "#FFC6FF", "#FFB5E8", "#85E3FF"]

    module_colours = {module: colours[i % len(colours)] for i, module in enumerate(all_modules)}

    def replace_none_with_blank(rows):
        processed_rows = []
        for row in rows:
            row = list(row) 
            if row[2]:
                row[2] = row[2].strftime('%d %B')
            row[1] = int(row[1]) if row[1] is not None else ""  
            row[3] = "Yes" if row[3] else ""        
            processed_rows.append(row)
        return processed_rows

    cur.execute("""SELECT module, weight, date, group_work, days_left
                   FROM Deadlines WHERE Year = %s AND days_left >= 0 order by date""", (user_year,))
    dl = replace_none_with_blank(cur.fetchall())

    return render_template("deadlines.html", Deadlines=dl, module_colours=module_colours)

def studyinfo(user_id, cur):
    cur.execute("""
        SELECT SUM(Hours + (Mins / 60.0)) 
        FROM Study_Log 
        WHERE UserID = %s
    """, (user_id,))
    total_hours = cur.fetchone()[0] or 0

    today = datetime.now()
    days_since_monday = today.weekday() 
    this_week_monday = datetime.combine((today - timedelta(days=days_since_monday)).date(), datetime.min.time())

    cur.execute("""
        SELECT SUM(Hours + (Mins / 60.0)) 
        FROM Study_Log 
        WHERE UserID = %s AND Date >= %s
    """, (user_id, this_week_monday.strftime('%Y-%m-%d %H:%M:%S')))

    total_week_hours = cur.fetchone()[0] or 0

    if total_week_hours >= 20:
        badge = "Platinum"
    elif total_week_hours >= 15:
        badge = "Gold"
    elif total_week_hours >= 10:
        badge = "Silver"
    elif total_week_hours >= 5:
        badge = "Bronze"
    else:
        badge = "Keep studying!"

    cur.execute("""
        SELECT DISTINCT Date
        FROM Study_Log
        WHERE UserID = %s AND (Hours > 0 OR Mins > 0)
        ORDER BY Date DESC
    """, (user_id,))
    study_dates = [row[0] for row in cur.fetchall()]

    streak = 0
    for i, log_date in enumerate(study_dates):
        expected_date = today.date() - timedelta(days=i)
        if log_date == expected_date:
            streak += 1
        else:
            break  

    return total_hours, total_week_hours, badge, streak

def format_date(date_obj):
    return date_obj.strftime("%d %B %Y")

@app.route('/studylogs', methods=['Get', 'Post'])
@login_required
def studylog():
    user_id = current_user.id

    #manual
    hours_logged = request.form.get('hours_logged', type=int, default = 0)
    minutes_logged = request.form.get('minutes_logged', type=int, default = 0)
    date_logged = datetime.now().strftime('%Y-%m-%d')

    if hours_logged > 0 or minutes_logged > 0:
            cur.execute("""
                INSERT INTO Study_Log (UserID, Date, Hours, Mins) 
                VALUES (%s, %s, %s, %s)
            """, (user_id, date_logged, hours_logged, minutes_logged))

    conn.commit()

    total_hours, total_week_hours, badge, streak = studyinfo(user_id, cur)

    cur.execute("SELECT Date, Hours, Mins FROM Study_Log WHERE UserID = %s order by Date desc", (user_id,))
    logs = cur.fetchall()

    logs = [(format_date(log[0]), log[1], log[2]) for log in logs]

    level = round(total_hours/10)
    
    return render_template("studylogs.html", total_week_hours=total_week_hours, badge=badge, streak=streak, logs=logs, level=level)

@app.route('/tasks', methods=['GET', 'POST'])
@login_required
def tasks():
    user_id = current_user.id

    if request.method == 'POST':
        task = request.form.get('task')

        def clean_input(value):
            return value.strip() if value and value.strip() else None

        notes = clean_input(request.form.get('notes'))
        due_date = clean_input(request.form.get('due_date'))

        remove = request.form.get('remove')

        if task:
            cur.execute("""
                INSERT INTO Tasks (UserID, Task, Notes, Due_Date) 
                VALUES (%s, %s, %s, %s)
            """, (user_id, task, notes, due_date))
            conn.commit()

        if remove:
            cur.execute("""
                DELETE FROM Tasks WHERE UserID = %s AND Task = %s
            """, (user_id, remove))
            conn.commit()

    cur.execute("SELECT Task FROM Tasks WHERE UserID = %s", (user_id,))
    tasks = cur.fetchall()

    cur.execute("SELECT Task, Notes, Due_Date FROM Tasks WHERE UserID = %s", (user_id,))
    task_list = cur.fetchall()

    return render_template("tasks.html", tasks=tasks, task_list=task_list)


app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'smhueffer@gmail.com'
app.config['MAIL_PASSWORD'] = 'ncpu higc mtgl lyng'
app.config['MAIL_DEFAULT_SENDER'] = 'smhueffer@gmail.com'

mail = Mail(app)

@app.route('/getintouch', methods=['GET', 'POST'])
@login_required
def get_in_touch():
    user_id = current_user.id
    cur.execute(f"select Year from users where id = %s", (user_id,))
    user_year = cur.fetchone()[0] 

    if request.method == 'POST':
        message_content = request.form.get('message')

        user = getattr(current_user, 'username', f'User ID {current_user.id}')

        msg = Message(subject=f'New Message from {user}',
                      recipients=['smhueffer@gmail.com']) 
        msg.body = f"""
        New message from a user:

        From: {user} ID: {user_id} Year: {user_year}

        Message:
        {message_content}
        """

        try:
            mail.send(msg)
            flash('Message sent! Thanks for reaching out.', 'success')
        except Exception as e:
            flash(f'Could not send message: {str(e)}', 'danger')

        return redirect(url_for('get_in_touch'))

    return render_template("getintouch.html", user_year=user_year)

@app.route('/examtimetable', methods=['GET', 'POST'])
@login_required
def exam_timetable():
    user_id = current_user.id
    cur.execute(f"select Year from users where id = %s", (user_id,))
    user_year = cur.fetchone()[0] 

    cur.execute("""SELECT Module, Date, Time
                   FROM Exam_Timetable WHERE Year = %s""", (user_year,))
    exam = cur.fetchall() 

    exam = [(log[0], format_date(log[1]), log[2]) for log in exam]

    return render_template("examtimetable.html", exam=exam)

@app.route('/favicon.ico')
def favicon():
    return '', 204

if __name__ == '__main__':
    app.run(debug=True)