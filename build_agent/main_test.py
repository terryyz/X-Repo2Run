import os
import json
import shutil
from utils.sandbox import Sandbox
from agents.simple_agent import Configuration

def main():
    # Define paths
    root_path = 'build_agent'  # Adjust this path as necessary
    full_name = 'demo_author/web_dashboard'
    fake_repo_path = f'{root_path}/utils/repo/{full_name}/repo'
    
    # Create a more complex fake repository directory structure
    os.makedirs(fake_repo_path, exist_ok=True)
    
    # Create subdirectories
    os.makedirs(f'{fake_repo_path}/static/css', exist_ok=True)
    os.makedirs(f'{fake_repo_path}/static/js', exist_ok=True)
    os.makedirs(f'{fake_repo_path}/templates', exist_ok=True)
    
    # Create a README.md with instructions
    with open(f'{fake_repo_path}/README.md', 'w') as f:
        f.write('''# Data Dashboard

A simple web dashboard for visualizing data analytics.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the application:
   ```
   python app.py
   ```

The dashboard will be available at http://localhost:5000

## Configuration

You can configure the port in `config.py`.
''')
    
    # Create a simple Flask application
    with open(f'{fake_repo_path}/app.py', 'w') as f:
        f.write('''from flask import Flask, render_template
import pandas as pd
from config import PORT

app = Flask(__name__)

@app.route('/')
def index():
    # Create some sample data
    data = {'Category': ['A', 'B', 'C', 'D'],
            'Values': [10, 20, 30, 40]}
    df = pd.DataFrame(data)
    
    # Pass data to template
    return render_template('index.html', 
                           title='Data Dashboard',
                           categories=df['Category'].tolist(),
                           values=df['Values'].tolist())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
''')
    
    # Create a config file
    with open(f'{fake_repo_path}/config.py', 'w') as f:
        f.write('''# Application configuration
PORT = 5000
''')
    
    # Create a simple template
    with open(f'{fake_repo_path}/templates/index.html', 'w') as f:
        f.write('''<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <div class="container">
        <h1>{{ title }}</h1>
        <div id="chart">
            <!-- Chart will be rendered here -->
        </div>
    </div>
    <script src="{{ url_for('static', filename='js/main.js') }}"></script>
</body>
</html>
''')
    
    # Create a CSS file
    with open(f'{fake_repo_path}/static/css/style.css', 'w') as f:
        f.write('''body {
    font-family: Arial, sans-serif;
    margin: 0;
    padding: 20px;
}
.container {
    max-width: 800px;
    margin: 0 auto;
}
#chart {
    height: 400px;
    border: 1px solid #ddd;
    margin-top: 20px;
}
''')
    
    # Create a JS file
    with open(f'{fake_repo_path}/static/js/main.js', 'w') as f:
        f.write('''// Simple chart visualization
document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard loaded');
    // In a real app, this would create a chart
    document.getElementById('chart').innerHTML = '<p>Chart visualization would appear here</p>';
});
''')
    
    # Create requirements.txt
    with open(f'{fake_repo_path}/requirements.txt', 'w') as f:
        f.write('''flask
pandas
numpy
matplotlib
''')
    
    # Create output directory if it doesn't exist
    os.makedirs(f'{root_path}/output/{full_name}', exist_ok=True)
    
    # Initialize trajectory
    trajectory = []
    
    # Set up sandbox and agent
    configuration_sandbox = Sandbox("python:3.10", full_name, root_path)
    configuration_sandbox.start_container()
    configuration_agent = Configuration(configuration_sandbox, 'python:3.10', full_name, root_path, max_turn=5)
    
    # Run the agent
    try:
        msg, outer_commands = configuration_agent.run(fake_repo_path, trajectory, [], [])
        
        # Print output for testing
        print("Trajectory:", json.dumps(trajectory[-1], indent=4))
        print("Outer commands:", json.dumps(outer_commands[-5:], indent=4))
    finally:
        # Clean up
        configuration_sandbox.stop_container()
        # Uncomment this line if you want to remove the fake repo after testing
        # shutil.rmtree(fake_repo_path, ignore_errors=True)

if __name__ == '__main__':
    main()