from flask import Flask, request, render_template
import subprocess

app = Flask(__name__)
ALLOWED_HOST = "192.168.199.5"

@app.before_request
def limit_remote_addr():
    if request.remote_addr != ALLOWED_HOST:
        return "You're not allowed to access this resource", 403

@app.route('/')
def display_journalctl():
    try:
        # Run the journalctl command and capture the output
        result = subprocess.check_output(['tail', '-n', '50', '/var/log/connection.log'])


        # Decode the output as UTF-8
        result = result.decode('utf-8')

        # Render the result in an HTML template
        return render_template('journalctl.html', result=result)
    except subprocess.CalledProcessError as e:
        # Handle the case where the command fails
        return f"Error running journalctl: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=False) 
