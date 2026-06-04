module.exports = {
  apps: [
    {
      name: "auto-trader-dashboard",
      script: ".venv/bin/python",
      args: "-m streamlit run dashboard/app.py --server.port 8501 --server.headless true",
      interpreter: "none",
      cwd: "/app/auto-trader",

      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,

      out_file: "logs/dashboard_out.log",
      error_file: "logs/dashboard_err.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      merge_logs: true,

      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONIOENCODING: "utf-8",
      },
    },
  ],
};
