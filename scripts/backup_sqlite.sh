#!/bin/bash
# SQLite Database Backup Script for HLD Generator v2
# This script creates timestamped backups of the SQLite database
# Run via cron for automated backups

set -e  # Exit on error

# Configuration
DB_FILE="${DB_FILE:-./hld_generator.db}"
BACKUP_DIR="${BACKUP_DIR:-./backups/database}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"  # Keep backups for 30 days
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/hld_generator_$TIMESTAMP.db"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=============================================="
echo "SQLite Database Backup"
echo "=============================================="

# Check if database exists
if [ ! -f "$DB_FILE" ]; then
    echo -e "${RED}Error: Database file not found: $DB_FILE${NC}"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Get database size
DB_SIZE=$(du -h "$DB_FILE" | cut -f1)
echo -e "${YELLOW}Database:${NC} $DB_FILE ($DB_SIZE)"
echo -e "${YELLOW}Backup to:${NC} $BACKUP_FILE"

# Create backup using SQLite's .backup command (online backup, safe while DB is in use)
echo -e "\n${YELLOW}Creating backup...${NC}"
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"

if [ $? -eq 0 ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo -e "${GREEN}✓ Backup completed successfully: $BACKUP_SIZE${NC}"

    # Verify backup integrity
    echo -e "\n${YELLOW}Verifying backup integrity...${NC}"
    sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" > /dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Backup integrity verified${NC}"
    else
        echo -e "${RED}✗ Backup integrity check failed${NC}"
        exit 1
    fi

    # Compress backup
    echo -e "\n${YELLOW}Compressing backup...${NC}"
    gzip -f "$BACKUP_FILE"
    COMPRESSED_SIZE=$(du -h "$BACKUP_FILE.gz" | cut -f1)
    echo -e "${GREEN}✓ Compressed to: $COMPRESSED_SIZE${NC}"

    # Clean up old backups
    echo -e "\n${YELLOW}Cleaning up backups older than $RETENTION_DAYS days...${NC}"
    find "$BACKUP_DIR" -name "hld_generator_*.db.gz" -type f -mtime +$RETENTION_DAYS -delete
    REMAINING_BACKUPS=$(find "$BACKUP_DIR" -name "hld_generator_*.db.gz" -type f | wc -l)
    echo -e "${GREEN}✓ Retained backups: $REMAINING_BACKUPS${NC}"

    # Calculate total backup size
    TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
    echo -e "${YELLOW}Total backup size:${NC} $TOTAL_SIZE"

else
    echo -e "${RED}✗ Backup failed${NC}"
    exit 1
fi

echo ""
echo "=============================================="
echo "Backup Complete!"
echo "=============================================="
echo "Latest backup: $BACKUP_FILE.gz"
echo ""

# Exit successfully
exit 0
