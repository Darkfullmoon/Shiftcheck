-- Shiftcheck database schema (MySQL 8+). Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS checklist_templates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(120) NOT NULL,
    description     VARCHAR(500) NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    is_default      TINYINT(1) NOT NULL DEFAULT 0,
    photo_min       INT NOT NULL DEFAULT 0,
    photo_max       INT NOT NULL DEFAULT 7,
    created_by      VARCHAR(50) NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS checklist_sections (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    template_id     INT NOT NULL,
    title           VARCHAR(200) NOT NULL,
    position        INT NOT NULL DEFAULT 0,
    CONSTRAINT fk_sections_template FOREIGN KEY (template_id)
        REFERENCES checklist_templates (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS checklist_items (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    section_id      INT NOT NULL,
    title           VARCHAR(500) NOT NULL,
    guidance        VARCHAR(500) NULL,
    position        INT NOT NULL DEFAULT 0,
    evidence_fields JSON NULL,
    CONSTRAINT fk_items_section FOREIGN KEY (section_id)
        REFERENCES checklist_sections (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS branches (
    id                        INT AUTO_INCREMENT PRIMARY KEY,
    name                      VARCHAR(100) NOT NULL UNIQUE,
    code                      VARCHAR(20) NULL,
    is_active                 TINYINT(1) NOT NULL DEFAULT 1,
    cleaning_schedule_enabled TINYINT(1) NOT NULL DEFAULT 0,
    template_id               INT NULL,
    created_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_branches_template FOREIGN KEY (template_id)
        REFERENCES checklist_templates (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    username             VARCHAR(32) NOT NULL UNIQUE,
    full_name            VARCHAR(100) NULL,
    password_hash        VARCHAR(255) NOT NULL,
    role                 VARCHAR(10) NOT NULL DEFAULT 'USER',
    branch_id            INT NULL,
    must_change_password TINYINT(1) NOT NULL DEFAULT 1,
    password_changed_at  TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at        TIMESTAMP NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_users_branch FOREIGN KEY (branch_id)
        REFERENCES branches (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS site_audits (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    branch_id       INT NOT NULL,
    template_id     INT NULL,
    template_name   VARCHAR(120) NOT NULL,
    audit_date      DATE NOT NULL,
    submitted_by    VARCHAR(32) NOT NULL,
    total_items     INT NOT NULL DEFAULT 0,
    passed_items    INT NOT NULL DEFAULT 0,
    failed_items    INT NOT NULL DEFAULT 0,
    na_items        INT NOT NULL DEFAULT 0,
    notes           TEXT NULL,
    payload         JSON NOT NULL,
    summary_text    MEDIUMTEXT NULL,
    summary_source  VARCHAR(10) NULL,
    photo_check     JSON NULL,
    is_verified     TINYINT(1) NOT NULL DEFAULT 0,
    headcount_ok    TINYINT(1) NOT NULL DEFAULT 0,
    dress_code_ok   TINYINT(1) NOT NULL DEFAULT 0,
    verified_by     VARCHAR(32) NULL,
    verified_at     TIMESTAMP NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audits_branch_date (branch_id, audit_date),
    INDEX idx_audits_date (audit_date),
    CONSTRAINT fk_audits_branch FOREIGN KEY (branch_id) REFERENCES branches (id),
    CONSTRAINT fk_audits_template FOREIGN KEY (template_id)
        REFERENCES checklist_templates (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS shift_reports (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    branch_id       INT NOT NULL,
    team            VARCHAR(100) NULL,
    report_date     DATE NOT NULL,
    submitted_by    VARCHAR(32) NOT NULL,
    briefing        JSON NULL,
    summary         JSON NULL,
    extra_tasks     TEXT NULL,
    staffing        JSON NULL,
    visitor_stats   JSON NULL,
    signoffs        JSON NULL,
    photos          JSON NULL,
    photo_check     JSON NULL,
    is_verified     TINYINT(1) NOT NULL DEFAULT 0,
    headcount_ok    TINYINT(1) NOT NULL DEFAULT 0,
    dress_code_ok   TINYINT(1) NOT NULL DEFAULT 0,
    verified_by     VARCHAR(32) NULL,
    verified_at     TIMESTAMP NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_reports_branch_date (branch_id, report_date),
    INDEX idx_reports_date (report_date),
    CONSTRAINT fk_reports_branch FOREIGN KEY (branch_id) REFERENCES branches (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cleaning_tasks (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    time_slot   VARCHAR(40) NULL,
    frequency   VARCHAR(10) NOT NULL DEFAULT 'DAILY',
    is_break    TINYINT(1) NOT NULL DEFAULT 0,
    position    INT NOT NULL DEFAULT 0,
    is_active   TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cleaning_schedules (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    branch_id     INT NOT NULL,
    month         CHAR(7) NOT NULL,
    submitted_by  VARCHAR(32) NOT NULL,
    data          JSON NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cleaning_branch_month (branch_id, month),
    CONSTRAINT fk_cleaning_branch FOREIGN KEY (branch_id) REFERENCES branches (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item_requests (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    branch_id     INT NULL,
    item_code     VARCHAR(50) NOT NULL,
    item_name     VARCHAR(255) NOT NULL,
    category      VARCHAR(100) NOT NULL,
    quantity      INT NOT NULL DEFAULT 1,
    reason        VARCHAR(500) NULL,
    submitted_by  VARCHAR(32) NOT NULL,
    status        VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    reviewer_note TEXT NULL,
    reviewed_by   VARCHAR(32) NULL,
    reviewed_at   TIMESTAMP NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_requests_status (status),
    CONSTRAINT fk_requests_branch FOREIGN KEY (branch_id)
        REFERENCES branches (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
