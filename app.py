from flask import Flask, jsonify
import datetime

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'success',
        'message': 'Server is running',
        'timestamp': datetime.datetime.now().isoformat()
    }), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)