import subprocess
import re

def get_ping_loss(hostname):
    try:
        # Run the fping command and capture its output
        result = subprocess.run(['fping', '-c', '3', hostname], capture_output=True, text=True, check=True)

        # Parse the output to extract the percentage loss
        pattern = r'(\d+)% loss'
        match = re.search(pattern, result.stdout)
        if match:
            loss_percentage = int(match.group(1))
            return loss_percentage
        else:
            raise ValueError("Unable to parse fping output for loss percentage")

    except subprocess.CalledProcessError as e:
        print(f"Error running fping. Return code: {e.returncode}")
        print(f"Error output: {e.output}")
        return None

# Example usage
hostname = '8.8.8.8'
loss_percentage = get_ping_loss(hostname)

if loss_percentage is not None:
    print(f"The packet loss to {hostname} is {loss_percentage}%.")
else:
    print(f"Failed to retrieve packet loss percentage for {hostname}.")
