# Arati Hotel Billing - Shell shortcuts
# Source this file in your shell: source /path/to/arati-hotel-billing/arati-shortcuts.sh
# Or add to your ~/.bashrc or ~/.zshrc:
#   source /home/ayushkli/Desktop/arati-hotel-billing/arati-shortcuts.sh

# Get the directory where this script is located
ARATI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Database initialization shortcut
alias arati-db-init="$ARATI_ROOT/db-init.sh"

# Start web application shortcut
alias arati-start="$ARATI_ROOT/start-web.sh"

# Stop web application (if running in background)
alias arati-stop="pkill -f 'uvicorn webapp.main:app' 2>/dev/null && echo 'Arati Hotel Web Billing stopped' || echo 'No running instance found'"

# View web application logs
alias arati-logs="tail -f $ARATI_ROOT/.run/web.log 2>/dev/null || echo 'No log file found at $ARATI_ROOT/.run/web.log'"

# Quick status check
alias arati-status="curl -fsS http://127.0.0.1:8000/login >/dev/null 2>&1 && echo 'Arati Hotel Web Billing is RUNNING at http://127.0.0.1:8000' || echo 'Arati Hotel Web Billing is NOT RUNNING'"

echo "Arati Hotel Billing shortcuts loaded:"
echo "  arati-db-init  - Initialize/seed the database"
echo "  arati-start    - Start the web application and open browser"
echo "  arati-stop     - Stop the web application"
echo "  arati-logs     - View live logs"
echo "  arati-status   - Check if web app is running"