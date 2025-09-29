from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import bcrypt
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# MongoDB setup
client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
db = client['attendance_db']
users_collection = db['users']
attendances_collection = db['attendances']


# Utility functions
def hash_password(password):
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password, hashed_password):
    """Check if password matches hashed password"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))


# Authentication routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register new employee"""
    try:
        data = request.get_json()

        required_fields = ['email', 'password', 'first_name', 'last_name', 'employee_id']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Check if user already exists
        if users_collection.find_one({'email': data['email']}):
            return jsonify({'error': 'User already exists'}), 409

        if users_collection.find_one({'employee_id': data['employee_id']}):
            return jsonify({'error': 'Employee ID already exists'}), 409

        # Hash password and create user
        user_data = {
            'email': data['email'],
            'password': hash_password(data['password']),
            'first_name': data['first_name'],
            'last_name': data['last_name'],
            'employee_id': data['employee_id'],
            'role': data.get('role', 'employee'),
            'department': data.get('department', ''),
            'position': data.get('position', ''),
            'is_active': True,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        result = users_collection.insert_one(user_data)
        user_id = str(result.inserted_id)

        # Get user data without password
        user_data = users_collection.find_one({'_id': result.inserted_id}, {'password': 0})
        user_data['_id'] = str(user_data['_id'])

        return jsonify({
            'message': 'User registered successfully',
            'user': user_data,
            'user_id': user_id
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login employee"""
    try:
        data = request.get_json()

        if 'email' not in data or 'password' not in data:
            return jsonify({'error': 'Email and password required'}), 400

        user = users_collection.find_one({'email': data['email']})

        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401

        if not user.get('is_active', True):
            return jsonify({'error': 'Account is deactivated'}), 401

        if not check_password(data['password'], user['password']):
            return jsonify({'error': 'Invalid credentials'}), 401

        # Remove password from response
        user['_id'] = str(user['_id'])
        user.pop('password', None)

        return jsonify({
            'message': 'Login successful',
            'user': user
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/user/<user_id>', methods=['GET'])
def get_user(user_id):
    """Get user by ID"""
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)}, {'password': 0})
        if user:
            user['_id'] = str(user['_id'])
            return jsonify(user), 200
        return jsonify({'error': 'User not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Attendance routes
@app.route('/api/attendance', methods=['POST'])
def create_attendance():
    """Create or update attendance record"""
    try:
        data = request.get_json()

        required_fields = ['user_id', 'attendance_date', 'latitude', 'longitude']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Validate date format
        try:
            datetime.fromisoformat(data['attendance_date'].replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use ISO format'}), 400

        # Get user info
        user = users_collection.find_one({'_id': ObjectId(data['user_id'])})
        if not user:
            return jsonify({'error': 'User not found'}), 404

        current_time = datetime.utcnow().isoformat() + 'Z'

        # Check if attendance exists for this date and user
        existing_attendance = attendances_collection.find_one({
            'user_id': data['user_id'],
            'attendance_date': data['attendance_date']
        })

        if existing_attendance:
            # Check if outtime already exists
            if existing_attendance.get('outtime'):
                return jsonify({
                    'error': 'Attendance already completed for this date',
                    'attendance_id': str(existing_attendance['_id'])
                }), 409

            # Update outtime
            result = attendances_collection.update_one(
                {'_id': existing_attendance['_id']},
                {'$set': {
                    'outtime': current_time,
                    'out_latitude': data['latitude'],
                    'out_longitude': data['longitude'],
                    'updated_at': datetime.utcnow()
                }}
            )

            if result.modified_count > 0:
                return jsonify({
                    'message': 'Outtime recorded successfully',
                    'type': 'outtime',
                    'attendance_id': str(existing_attendance['_id'])
                }), 200

        else:
            # Create new attendance with intime
            attendance_data = {
                'user_id': data['user_id'],
                'employee_id': user.get('employee_id', ''),
                'employee_name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                'attendance_date': data['attendance_date'],
                'intime': current_time,
                'in_latitude': data['latitude'],
                'in_longitude': data['longitude'],
                'outtime': None,
                'out_latitude': None,
                'out_longitude': None,
                'location_name': data.get('location_name', ''),
                'notes': data.get('notes', ''),
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }

            result = attendances_collection.insert_one(attendance_data)
            attendance_id = str(result.inserted_id)

            return jsonify({
                'message': 'Intime recorded successfully',
                'type': 'intime',
                'attendance_id': attendance_id
            }), 201

        return jsonify({'error': 'Failed to process attendance'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/<attendance_id>', methods=['GET'])
def get_attendance(attendance_id):
    """Get specific attendance record"""
    try:
        attendance = attendances_collection.find_one({'_id': ObjectId(attendance_id)})

        if not attendance:
            return jsonify({'error': 'Attendance not found'}), 404

        attendance['_id'] = str(attendance['_id'])
        return jsonify(attendance), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendances', methods=['GET'])
def get_attendances():
    """Get all attendances grouped by employee and date"""
    try:
        # Get all users
        users = list(users_collection.find({}, {'password': 0}))

        # Get all attendances
        attendances = list(attendances_collection.find().sort('attendance_date', -1))

        # Group attendances by employee and date
        employee_attendance_map = {}

        for user in users:
            user_id = str(user['_id'])
            employee_attendance_map[user_id] = {
                'employee_id': user.get('employee_id', ''),
                'employee_name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                'email': user.get('email', ''),
                'department': user.get('department', ''),
                'position': user.get('position', ''),
                'attendance_dates': {}
            }

        for attendance in attendances:
            user_id = attendance['user_id']
            if user_id in employee_attendance_map:
                date = attendance['attendance_date']

                if date not in employee_attendance_map[user_id]['attendance_dates']:
                    employee_attendance_map[user_id]['attendance_dates'][date] = {
                        'date': date,
                        'intime': attendance.get('intime'),
                        'outtime': attendance.get('outtime'),
                        'in_location': {
                            'latitude': attendance.get('in_latitude'),
                            'longitude': attendance.get('in_longitude')
                        },
                        'out_location': {
                            'latitude': attendance.get('out_latitude'),
                            'longitude': attendance.get('out_longitude')
                        },
                        'last_updated': attendance.get('updated_at'),
                        'status': 'present' if attendance.get('intime') else 'absent'
                    }

        # Convert to list format
        result = []
        for user_id, data in employee_attendance_map.items():
            # Convert dates dict to sorted list
            dates_list = sorted(
                list(data['attendance_dates'].values()),
                key=lambda x: x['date'],
                reverse=True
            )

            result.append({
                'user_id': user_id,
                'employee_id': data['employee_id'],
                'employee_name': data['employee_name'],
                'email': data['email'],
                'department': data['department'],
                'position': data['position'],
                'attendance_dates': dates_list,
                'total_days': len(dates_list),
                'present_days': sum(1 for d in dates_list if d['status'] == 'present')
            })

        return jsonify({'employees': result}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/employee/<user_id>/attendances', methods=['GET'])
def get_employee_attendances(user_id):
    """Get attendances for specific employee"""
    try:
        # Get user info
        user = users_collection.find_one({'_id': ObjectId(user_id)}, {'password': 0})
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Get attendances for this user
        attendances = list(attendances_collection.find({'user_id': user_id}).sort('attendance_date', -1))

        # Group by date
        attendance_dates = {}
        for attendance in attendances:
            date = attendance['attendance_date']
            attendance_dates[date] = {
                'date': date,
                'intime': attendance.get('intime'),
                'outtime': attendance.get('outtime'),
                'in_location': {
                    'latitude': attendance.get('in_latitude'),
                    'longitude': attendance.get('in_longitude')
                },
                'out_location': {
                    'latitude': attendance.get('out_latitude'),
                    'longitude': attendance.get('out_longitude')
                },
                'last_updated': attendance.get('updated_at'),
                'status': 'present' if attendance.get('intime') else 'absent'
            }

        # Convert to sorted list
        dates_list = sorted(
            list(attendance_dates.values()),
            key=lambda x: x['date'],
            reverse=True
        )

        result = {
            'user_id': user_id,
            'employee_id': user.get('employee_id', ''),
            'employee_name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            'email': user.get('email', ''),
            'department': user.get('department', ''),
            'position': user.get('position', ''),
            'attendance_dates': dates_list,
            'total_days': len(dates_list),
            'present_days': sum(1 for d in dates_list if d['status'] == 'present'),
            'attendance_percentage': (sum(1 for d in dates_list if d['status'] == 'present') / len(
                dates_list) * 100) if dates_list else 0
        }

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance/stats/<user_id>', methods=['GET'])
def get_attendance_stats(user_id):
    """Get attendance statistics for user"""
    try:
        # Get user info
        user = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Get attendances
        attendances = list(attendances_collection.find({'user_id': user_id}))

        # Group by date
        attendance_dates = {}
        for attendance in attendances:
            date = attendance['attendance_date']
            attendance_dates[date] = {
                'date': date,
                'intime': attendance.get('intime'),
                'outtime': attendance.get('outtime'),
                'in_location': {
                    'latitude': attendance.get('in_latitude'),
                    'longitude': attendance.get('in_longitude')
                },
                'out_location': {
                    'latitude': attendance.get('out_latitude'),
                    'longitude': attendance.get('out_longitude')
                },
                'last_updated': attendance.get('updated_at')
            }

        # Convert to sorted list
        dates_list = sorted(
            list(attendance_dates.values()),
            key=lambda x: x['date'],
            reverse=True
        )

        # Calculate statistics
        total_days = len(dates_list)
        present_days = sum(1 for d in dates_list if d['intime'] is not None)

        stats = {
            'user_id': user_id,
            'employee_id': user.get('employee_id', ''),
            'employee_name': f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            'total_days': total_days,
            'present_days': present_days,
            'absent_days': total_days - present_days,
            'attendance_percentage': (present_days / total_days * 100) if total_days > 0 else 0,
            'attendance_dates': dates_list
        }

        return jsonify(stats), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users', methods=['GET'])
def get_all_users():
    """Get all users"""
    try:
        users = list(users_collection.find({}, {'password': 0}))
        for user in users:
            user['_id'] = str(user['_id'])
        return jsonify(users), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Utility routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}), 200


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5200)