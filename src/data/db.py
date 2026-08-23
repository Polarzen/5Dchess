"""
5D Chess - MySQL 数据库连接管理
"""
from __future__ import annotations
import mysql.connector
from mysql.connector import pooling
from src.config import DB_CONFIG
from src.utils.logger import logger


class DatabaseManager:
    """MySQL 连接管理器（连接池）"""

    _instance: DatabaseManager | None = None
    _pool: pooling.MySQLConnectionPool | None = None

    def __new__(cls) -> DatabaseManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._pool is None:
            self._init_pool()

    def _init_pool(self):
        """初始化连接池"""
        try:
            self._pool = pooling.MySQLConnectionPool(
                pool_name="chess_5d_pool",
                pool_size=5,
                pool_reset_session=True,
                **DB_CONFIG,
            )
            logger.info("数据库连接池初始化成功")
        except mysql.connector.Error as e:
            logger.warning(f"数据库连接失败（将使用文件存储）: {e}")
            self._pool = None

    @property
    def is_available(self) -> bool:
        return self._pool is not None

    def get_connection(self):
        """获取连接"""
        if self._pool is None:
            raise RuntimeError("数据库不可用")
        return self._pool.get_connection()

    def execute(self, sql: str, params: tuple = None) -> int:
        """执行SQL，返回影响行数"""
        if not self.is_available:
            return 0
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            conn.commit()
            return cursor.rowcount
        except mysql.connector.Error as e:
            logger.error(f"SQL执行失败: {e}")
            conn.rollback()
            return 0
        finally:
            conn.close()

    def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        """批量执行SQL"""
        if not self.is_available:
            return 0
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, params_list)
            conn.commit()
            return cursor.rowcount
        except mysql.connector.Error as e:
            logger.error(f"批量SQL执行失败: {e}")
            conn.rollback()
            return 0
        finally:
            conn.close()

    def query(self, sql: str, params: tuple = None) -> list[dict]:
        """查询，返回字典列表"""
        if not self.is_available:
            return []
        conn = self.get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params or ())
            return cursor.fetchall()
        except mysql.connector.Error as e:
            logger.error(f"查询失败: {e}")
            return []
        finally:
            conn.close()

    def query_one(self, sql: str, params: tuple = None) -> dict | None:
        """查询单行"""
        rows = self.query(sql, params)
        return rows[0] if rows else None


# 全局数据库管理器
db = DatabaseManager()