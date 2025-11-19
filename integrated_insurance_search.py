#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成保险文档搜索系统
结合qwen-agent前端界面和Elasticsearch后端检索功能
"""

import pprint
import urllib.parse
import json5
import os
import json
import logging
import requests
from qwen_agent.agents import Assistant
from qwen_agent.tools.base import BaseTool, register_tool
from qwen_agent.gui import WebUI
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== 配置区域 ==========
# 如果环境变量读取失败，可以在这里临时设置API Key（仅用于测试，不要提交到代码仓库）
# TAVILY_API_KEY_HARDCODED = "your-api-key-here"  # 取消注释并填入你的API Key
TAVILY_API_KEY_HARDCODED = None  # 默认不使用硬编码
# ==============================

class ElasticsearchManager:
    """Elasticsearch 管理器"""
    
    def __init__(self, es_host="localhost", es_port=9200, es_username="elastic", es_password="rT_bpz*daxmw8rabCrp8"):
        """
        初始化ES连接
        
        Args:
            es_host: ES主机地址
            es_port: ES端口
            es_username: ES用户名
            es_password: ES密码
        """
        self.es_host = es_host
        self.es_port = es_port
        
        # 构建ES连接配置 - 使用HTTPS
        es_config = {
            # 主机配置：指定ES服务器地址、端口和协议
            'hosts': [{'host': es_host, 'port': es_port, 'scheme': 'https'}],
            # 重试配置：连接失败时最多重试3次
            'max_retries': 3,
            # 超时重试：超时时自动重试连接
            'retry_on_timeout': True,
            # SSL证书验证：开发环境设为False，生产环境建议设为True
            'verify_certs': False,
            # SSL警告：禁用SSL警告信息显示
            'ssl_show_warn': False
        }
        
        # 认证配置：如果提供了用户名和密码，添加基本认证
        if es_username and es_password:
            # 使用基本认证方式连接ES（用户名+密码）
            es_config['basic_auth'] = (es_username, es_password)
        
        try:
            # 创建Elasticsearch客户端实例
            self.es = Elasticsearch(**es_config)
            
            # 测试连接：使用ping()方法检查ES服务是否可用
            if self.es.ping():
                logger.info(f"成功连接到Elasticsearch: {es_host}:{es_port}")
            else:
                # 连接失败：ping()返回False表示ES服务不可用
                raise Exception("无法连接到Elasticsearch")
        except Exception as e:
            # 异常处理：记录连接失败的错误信息并重新抛出异常
            logger.error(f"连接Elasticsearch失败: {str(e)}")
            raise
    
    def create_index(self, index_name="insurance_docs", mapping=None):
        """
        创建索引
        
        Args:
            index_name: 索引名称
            mapping: 索引映射配置
        """
        try:
            # 检查索引是否已存在
            if self.es.indices.exists(index=index_name):
                logger.info(f"索引 {index_name} 已存在，将删除并重新创建")
                self.es.indices.delete(index=index_name)
            
            # 默认映射配置 - 使用标准分析器
            if mapping is None:
                mapping = {
                    "mappings": {
                        "properties": {
                            "title": {
                                "type": "text",
                                "analyzer": "standard",
                                "fields": {
                                    "keyword": {
                                        "type": "keyword"
                                    }
                                }
                            },
                            "content": {
                                "type": "text",
                                "analyzer": "standard",
                                "fields": {
                                    "keyword": {
                                        "type": "keyword"
                                    }
                                }
                            },
                            "source": {
                                "type": "keyword"
                            },
                            "file_type": {
                                "type": "keyword"
                            },
                            "created_time": {
                                "type": "date"
                            }
                        }
                    },
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0
                    }
                }
            
            # 创建索引
            self.es.indices.create(index=index_name, body=mapping)
            logger.info(f"成功创建索引: {index_name}")
            return True
            
        except Exception as e:
            logger.error(f"创建索引失败: {str(e)}")
            return False
    
    def index_documents(self, docs_dir="docs", index_name="insurance_docs"):
        """
        索引文档
        
        Args:
            docs_dir: 文档目录
            index_name: 索引名称
        """
        try:
            documents = []
            
            # 遍历docs目录
            for filename in os.listdir(docs_dir):
                file_path = os.path.join(docs_dir, filename)
                
                # 只处理txt文件
                if filename.endswith('.txt') and os.path.isfile(file_path):
                    logger.info(f"正在处理文件: {filename}")
                    
                    # 读取文件内容
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 提取标题（从文件名或内容中）
                    title = filename.replace('.txt', '')
                    
                    # 构建文档
                    doc = {
                        "_index": index_name,
                        "_id": filename,  # 添加文档ID
                        "_source": {
                            "title": title,
                            "content": content,
                            "source": filename,
                            "file_type": "txt",
                            "created_time": "2024-12-19T00:00:00"
                        }
                    }
                    documents.append(doc)
            
            # 批量索引文档
            if documents:
                success_count, failed_items = bulk(self.es, documents)
                logger.info(f"成功索引 {success_count} 个文档")
                if failed_items:
                    logger.warning(f"失败项目: {failed_items}")
                
                # 强制刷新索引
                self.es.indices.refresh(index=index_name)
                logger.info(f"已刷新索引 {index_name}")
                
                # 验证索引结果
                stats = self.es.indices.stats(index=index_name)
                doc_count = stats['indices'][index_name]['total']['docs']['count']
                logger.info(f"验证：索引 {index_name} 现在包含 {doc_count} 个文档")
            else:
                logger.warning("未找到要索引的文档")
                
        except Exception as e:
            logger.error(f"索引文档失败: {str(e)}")
    
    def smart_search(self, search_query, index_name="insurance_docs", size=10):
        """智能搜索方法"""
        try:
            # 提取关键词
            keywords = []
            if "雇主责任险" in search_query:
                keywords.extend(["雇主责任险", "雇主", "责任险"])
            if "保障范围" in search_query:
                keywords.extend(["保障范围", "保障", "范围"])
            if "保险" in search_query:
                keywords.append("保险")
            
            # 构建多关键词搜索
            search_body = {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "multi_match": {
                                    "query": search_query,
                                    "fields": ["title^3", "content^2"],
                                    "type": "best_fields"
                                }
                            }
                        ] + [
                            {
                                "match": {
                                    "content": keyword
                                }
                            } for keyword in keywords
                        ]
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {},
                        "content": {
                            "fragment_size": 300,
                            "number_of_fragments": 5
                        }
                    }
                },
                "size": size
            }
            
            # 执行搜索
            response = self.es.search(index=index_name, body=search_body)
            
            # 处理搜索结果
            hits = response['hits']['hits']
            total_hits = response['hits']['total']['value']
            max_score = response['hits']['max_score']
            
            logger.info(f"智能搜索查询: '{search_query}'")
            logger.info(f"找到 {total_hits} 个相关文档")
            logger.info(f"最高评分: {max_score:.4f}")
            
            # 输出每个结果的评分
            for i, hit in enumerate(hits):
                score = hit['_score']
                title = hit['_source'].get('title', '无标题')
                logger.info(f"结果 {i+1}: {title} (评分: {score:.4f})")
            
            return response
            
        except Exception as e:
            logger.error(f"智能搜索失败: {str(e)}")
            return None

    def simple_bm25_search(self, search_query, index_name="insurance_docs", size=10):
        """简化的BM25搜索方法"""
        try:
            logger.info(f"🔍 执行简化BM25搜索: '{search_query}'")
            
            # 最简单的BM25搜索查询
            search_body = {
                "query": {
                    "multi_match": {
                        "query": search_query,
                        "fields": ["title^3", "content^2"],
                        "type": "best_fields"
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {},
                        "content": {}
                    }
                },
                "size": size
            }
            
            # 执行BM25搜索
            response = self.es.search(index=index_name, body=search_body)
            
            # 处理搜索结果
            hits = response['hits']['hits']
            total_hits = response['hits']['total']['value']
            max_score = response['hits']['max_score']
            
            logger.info(f"简化BM25搜索查询: '{search_query}'")
            logger.info(f"找到 {total_hits} 个相关文档 (最高分: {max_score:.4f})")
            
            # 输出每个结果的评分
            for i, hit in enumerate(hits):
                score = hit['_score']
                title = hit['_source'].get('title', '无标题')
                logger.info(f"BM25结果 {i+1}: {title} (评分: {score:.4f})")
            
            return response
            
        except Exception as e:
            logger.error(f"简化BM25搜索失败: {str(e)}")
            return None

    def hybrid_search(self, search_query, index_name="insurance_docs", size=10):
        """混合搜索方法 - 结合BM25和智能搜索"""
        try:
            logger.info(f"🔍 执行混合搜索: '{search_query}'")
            
            # 1. 先尝试简化BM25搜索
            bm25_results = self.simple_bm25_search(search_query, index_name, size)
            bm25_count = bm25_results['hits']['total']['value'] if bm25_results else 0
            bm25_max_score = bm25_results['hits']['max_score'] if bm25_results else 0
            
            # 2. 如果BM25搜索结果不足，尝试智能搜索
            smart_results = None
            if bm25_count < 3:
                logger.info("BM25搜索结果不足，尝试智能搜索补充")
                smart_results = self.smart_search(search_query, index_name, size)
                smart_count = smart_results['hits']['total']['value'] if smart_results else 0
                smart_max_score = smart_results['hits']['max_score'] if smart_results else 0
                
                if smart_count > 0:
                    logger.info(f"智能搜索找到 {smart_count} 个结果 (最高分: {smart_max_score:.4f})")
                    return smart_results
            
            # 3. 返回BM25结果
            if bm25_count > 0:
                logger.info(f"混合搜索完成：BM25找到 {bm25_count} 个结果 (最高分: {bm25_max_score:.4f})")
                return bm25_results
            elif smart_results and smart_results['hits']['total']['value'] > 0:
                smart_count = smart_results['hits']['total']['value']
                smart_max_score = smart_results['hits']['max_score']
                logger.info(f"混合搜索完成：智能搜索找到 {smart_count} 个结果 (最高分: {smart_max_score:.4f})")
                return smart_results
            else:
                logger.info("混合搜索：所有方法都没有找到结果")
                return None
                
        except Exception as e:
            logger.error(f"混合搜索失败: {str(e)}")
            return None

    def search_documents(self, search_query, index_name="insurance_docs", size=10):
        """
        搜索文档
        
        Args:
            search_query: 搜索查询
            index_name: 索引名称
            size: 返回结果数量
        """
        try:
            # 构建搜索查询 - 优化中文搜索
            search_body = {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "multi_match": {
                                    "query": search_query,
                                    "fields": ["title^3", "content^2"],
                                    "type": "best_fields",
                                    "fuzziness": "AUTO"
                                }
                            },
                            {
                                "match": {
                                    "title": {
                                        "query": search_query,
                                        "boost": 3
                                    }
                                }
                            },
                            {
                                "match": {
                                    "content": {
                                        "query": search_query,
                                        "boost": 2
                                    }
                                }
                            },
                            {
                                "wildcard": {
                                    "title": f"*{search_query}*"
                                }
                            },
                            {
                                "wildcard": {
                                    "content": f"*{search_query}*"
                                }
                            },
                            {
                                "match_phrase": {
                                    "title": search_query
                                }
                            },
                            {
                                "match_phrase": {
                                    "content": search_query
                                }
                            }
                        ]
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {},
                        "content": {
                            "fragment_size": 200,
                            "number_of_fragments": 3
                        }
                    }
                },
                "size": size
            }
            
            # 执行搜索
            response = self.es.search(index=index_name, body=search_body)
            
            # 处理搜索结果
            hits = response['hits']['hits']
            total_hits = response['hits']['total']['value']
            max_score = response['hits']['max_score']
            
            logger.info(f"搜索查询: '{search_query}'")
            logger.info(f"找到 {total_hits} 个相关文档 (最高分: {max_score:.4f})")
            
            # 输出每个结果的评分
            for i, hit in enumerate(hits):
                score = hit['_score']
                title = hit['_source'].get('title', '无标题')
                logger.info(f"普通搜索结果 {i+1}: {title} (评分: {score:.4f})")
            
            return response
            
        except Exception as e:
            logger.error(f"搜索失败: {str(e)}")
            return None

    def get_index_info(self, index_name="insurance_docs"):
        """获取索引信息"""
        try:
            # 检查索引是否存在
            if not self.es.indices.exists(index=index_name):
                logger.error(f"索引 {index_name} 不存在")
                return 0
            
            stats = self.es.indices.stats(index=index_name)
            doc_count = stats['indices'][index_name]['total']['docs']['count']
            logger.info(f"索引 {index_name} 包含 {doc_count} 个文档")
            
            return doc_count
        except Exception as e:
            logger.error(f"获取索引信息失败: {str(e)}")
            return 0


# 全局ES管理器实例
es_manager = None

# 步骤 1：添加保险文档搜索工具
@register_tool('insurance_doc_search')
class InsuranceDocSearch(BaseTool):
    # `description` 用于告诉智能体该工具的功能。
    description = '保险文档搜索服务，根据用户查询搜索相关的保险文档内容，支持智能搜索、BM25搜索和混合搜索策略。'
    # `parameters` 告诉智能体该工具有哪些输入参数。
    parameters = [{
        'name': 'query',
        'type': 'string',
        'description': '用户搜索查询，可以是保险相关的任何问题',
        'required': True
    }, {
        'name': 'search_type',
        'type': 'string',
        'description': '搜索类型：smart（智能搜索）、bm25（BM25搜索）、hybrid（混合搜索）、normal（普通搜索）',
        'required': False
    }, {
        'name': 'size',
        'type': 'integer',
        'description': '返回结果数量，默认10',
        'required': False
    }]

    def call(self, params: str, **kwargs) -> str:
        # `params` 是由 LLM 智能体生成的参数。
        print(f"🔍 DEBUG: insurance_doc_search 工具被调用！")
        print(f"🔍 DEBUG: 接收到的参数: {params}")
        try:
            params_dict = json5.loads(params)
            query = params_dict['query']
            search_type = params_dict.get('search_type', 'hybrid')
            size = params_dict.get('size', 10)
            print(f"🔍 DEBUG: 解析后的查询: {query}, 搜索类型: {search_type}")
            
            # 使用全局ES管理器进行搜索
            global es_manager
            if not es_manager:
                print(f"❌ DEBUG: Elasticsearch管理器未初始化")
                return json5.dumps({'error': 'Elasticsearch管理器未初始化'}, ensure_ascii=False)
            
            print(f"🔍 DEBUG: 开始执行搜索，搜索类型: {search_type}")
            
            # 根据搜索类型执行不同的搜索策略
            try:
                if search_type == 'smart':
                    results = es_manager.smart_search(query, size=size)
                elif search_type == 'bm25':
                    results = es_manager.simple_bm25_search(query, size=size)
                elif search_type == 'normal':
                    results = es_manager.search_documents(query, size=size)
                else:  # hybrid
                    results = es_manager.hybrid_search(query, size=size)
                
                print(f"🔍 DEBUG: 搜索完成，结果: {results is not None}")
                
                if not results:
                    print(f"❌ DEBUG: 搜索结果为空")
                    return json5.dumps({'error': '搜索失败或未找到相关文档'}, ensure_ascii=False)
                    
            except Exception as search_error:
                print(f"❌ DEBUG: 搜索过程中出现错误: {str(search_error)}")
                return json5.dumps({'error': f'搜索过程中出现错误: {str(search_error)}'}, ensure_ascii=False)
            
            # 处理搜索结果
            try:
                hits = results['hits']['hits']
                total_hits = results['hits']['total']['value']
                max_score = results['hits']['max_score']
                print(f"🔍 DEBUG: 找到 {total_hits} 个结果，处理 {len(hits)} 个文档")
                print(f"🔍 DEBUG: 最高评分: {max_score:.4f}")
                
                # 格式化搜索结果
                search_results = []
                for i, hit in enumerate(hits):
                    source = hit['_source']
                    score = hit['_score']
                    result_item = {
                        'title': source.get('title', '无标题'),
                        'content': source.get('content', ''),
                        'source': source.get('source', '未知'),
                        'score': score,
                        'score_percentage': f"{(score/max_score*100):.1f}%" if max_score > 0 else "0%",
                        'highlights': hit.get('highlight', {})
                    }
                    search_results.append(result_item)
                    print(f"🔍 DEBUG: 处理文档 {i+1}: {result_item['title']} (评分: {score:.4f}, 相对评分: {result_item['score_percentage']})")
                
                # 输出详细的评分统计信息
                print(f"\n📊 搜索结果评分统计:")
                print(f"   总结果数: {total_hits}")
                print(f"   最高评分: {max_score:.4f}")
                print(f"   平均评分: {sum(hit['_score'] for hit in hits)/len(hits):.4f}" if hits else "   平均评分: 0.0000")
                print(f"   评分范围: {min(hit['_score'] for hit in hits):.4f} - {max_score:.4f}" if hits else "   评分范围: 0.0000 - 0.0000")
                
                result_json = json5.dumps({
                    'query': query,
                    'search_type': search_type,
                    'total_hits': total_hits,
                    'max_score': max_score,
                    'score_stats': {
                        'max_score': max_score,
                        'avg_score': sum(hit['_score'] for hit in hits)/len(hits) if hits else 0,
                        'min_score': min(hit['_score'] for hit in hits) if hits else 0,
                        'score_range': f"{min(hit['_score'] for hit in hits):.4f} - {max_score:.4f}" if hits else "0.0000 - 0.0000"
                    },
                    'results': search_results
                }, ensure_ascii=False)
                
                print(f"🔍 DEBUG: 返回结果长度: {len(result_json)} 字符")
                return result_json
                
            except Exception as process_error:
                print(f"❌ DEBUG: 处理搜索结果时出现错误: {str(process_error)}")
                return json5.dumps({'error': f'处理搜索结果时出现错误: {str(process_error)}'}, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"保险文档搜索失败: {str(e)}")
            return json5.dumps({'error': f'搜索失败: {str(e)}'}, ensure_ascii=False)


# 步骤 2：添加图像生成工具
@register_tool('my_image_gen')
class MyImageGen(BaseTool):
    # `description` 用于告诉智能体该工具的功能。
    description = 'AI 绘画（图像生成）服务，输入文本描述，返回基于文本信息绘制的图像 URL。'
    # `parameters` 告诉智能体该工具有哪些输入参数。
    parameters = [{
        'name': 'prompt',
        'type': 'string',
        'description': '期望的图像内容的详细描述',
        'required': True
    }]

    def call(self, params: str, **kwargs) -> str:
        # `params` 是由 LLM 智能体生成的参数。
        prompt = json5.loads(params)['prompt']
        prompt = urllib.parse.quote(prompt)
        return json5.dumps(
            {'image_url': f'https://image.pollinations.ai/prompt/{prompt}'},
            ensure_ascii=False)


@register_tool('tavily_mcp')
class TavilyMcpTool(BaseTool):
    """Tavily Web 搜索工具"""
    description = '调用Tavily MCP接口执行实时网页搜索，获取结构化搜索结果。'
    parameters = [{
        'name': 'query',
        'type': 'string',
        'description': '需要搜索的查询内容',
        'required': True
    }, {
        'name': 'search_depth',
        'type': 'string',
        'description': '搜索深度，可选值为basic或advanced，默认basic',
        'required': False
    }, {
        'name': 'max_results',
        'type': 'integer',
        'description': '最大返回结果数量，默认5，范围1-10',
        'required': False
    }]

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            query = args.get('query')
            if not query:
                logger.warning("Tavily工具: 查询内容为空")
                return '错误: 查询内容不能为空'

            # 多种方式尝试获取API Key
            api_key = None
            
            # 方式1: 优先使用硬编码的API Key
            if TAVILY_API_KEY_HARDCODED:
                api_key = TAVILY_API_KEY_HARDCODED
            
            # 方式2: 从环境变量读取
            if not api_key:
                api_key = os.getenv('TAVILY_API_KEY')
            
            # 方式3: 从os.environ直接读取
            if not api_key:
                api_key = os.environ.get('TAVILY_API_KEY')
            
            if not api_key:
                error_msg = '''未检测到Tavily API Key。请按以下步骤设置：

1. 访问 https://app.tavily.com/home 注册并获取API Key
2. 设置环境变量：
   Windows PowerShell: $env:TAVILY_API_KEY = "your-api-key"
   Windows CMD: set TAVILY_API_KEY=your-api-key
   Linux/Mac: export TAVILY_API_KEY="your-api-key"
3. 重启程序后生效

临时方案: 在代码开头设置 TAVILY_API_KEY_HARDCODED = "your-api-key"'''
                logger.error("Tavily API Key未设置")
                return error_msg

            search_depth = args.get('search_depth', 'basic')
            if search_depth not in ('basic', 'advanced'):
                search_depth = 'basic'

            max_results = args.get('max_results', 5)
            try:
                max_results = int(max_results)
            except (TypeError, ValueError):
                max_results = 5
            max_results = max(1, min(max_results, 10))

            request_body = {
                'query': query,
                'search_depth': search_depth,
                'max_results': max_results,
                'include_answer': True,
                'include_images': False,
                'include_raw_content': False
            }

            print(f"🔍 DEBUG: 发送Tavily请求，URL: https://api.tavily.com/search")
            print(f"🔍 DEBUG: 请求体: {json5.dumps(request_body, ensure_ascii=False)}")
            
            response = requests.post(
                'https://api.tavily.com/search',
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                json=request_body,
                timeout=20
            )
            
            print(f"🔍 DEBUG: Tavily响应状态码: {response.status_code}")
            
            # 检查HTTP状态码
            if response.status_code != 200:
                error_text = response.text[:500] if response.text else '无错误详情'
                logger.error(f"Tavily HTTP错误: 状态码={response.status_code}, 响应={error_text}")
                error_msg = f'错误: Tavily API请求失败，状态码: {response.status_code}'
                if error_text:
                    error_msg += f'\n错误详情: {error_text}'
                return error_msg
            
            # 解析响应
            try:
                data = response.json()
                print(f"🔍 DEBUG: Tavily响应解析成功，数据类型: {type(data)}")
                
                # 格式化返回结果，使其更易读
                if isinstance(data, dict):
                    # 安全提取关键信息，确保类型正确
                    results = data.get('results', [])
                    answer = data.get('answer', '')
                    
                    # 确保results是列表类型
                    if not isinstance(results, list):
                        logger.warning(f"results字段不是列表类型: {type(results)}，尝试转换")
                        try:
                            results = list(results) if results else []
                        except Exception as e:
                            logger.error(f"转换results为列表失败: {str(e)}")
                            results = []
                    
                    # 确保answer是字符串或None
                    if answer is not None and not isinstance(answer, str):
                        try:
                            answer = str(answer)
                        except Exception as e:
                            logger.warning(f"转换answer为字符串失败: {str(e)}")
                            answer = ''
                    
                    formatted_result = {
                        'query': query,
                        'answer': answer or '',
                        'results_count': len(results),
                        'results': results[:max_results] if results else []  # 限制返回数量
                    }
                    
                    # 构建可读的文本格式
                    result_text = f"搜索查询: {query}\n\n"
                    
                    # 安全处理答案摘要
                    if answer:
                        try:
                            # 确保answer是字符串类型，并清理特殊字符
                            answer_str = str(answer) if answer is not None else ''
                            # 移除可能导致问题的控制字符，但保留换行符
                            answer_str = ''.join(char for char in answer_str if ord(char) >= 32 or char in '\n\r\t')
                            if answer_str.strip():
                                result_text += f"答案摘要: {answer_str}\n\n"
                        except Exception as e:
                            logger.warning(f"处理答案摘要时出错: {str(e)}")
                    
                    # 安全处理搜索结果
                    if results:
                        result_text += f"找到 {len(results)} 个相关结果:\n\n"
                        for i, result in enumerate(results[:max_results], 1):
                            try:
                                # 确保result是字典类型
                                if not isinstance(result, dict):
                                    logger.warning(f"结果 {i} 不是字典类型: {type(result)}")
                                    continue
                                
                                # 安全获取并转换字段
                                title = result.get('title') or '无标题'
                                url = result.get('url') or ''
                                content_raw = result.get('content')
                                
                                # 确保所有字段都是字符串类型
                                title = str(title) if title is not None else '无标题'
                                url = str(url) if url is not None else ''
                                
                                # 安全处理content字段
                                content = ''
                                if content_raw is not None:
                                    try:
                                        content_str = str(content_raw)
                                        # 限制长度并清理特殊字符
                                        content = content_str[:200] if len(content_str) > 200 else content_str
                                        # 移除可能导致问题的控制字符，但保留换行符和制表符
                                        content = ''.join(char for char in content if ord(char) >= 32 or char in '\n\r\t')
                                    except Exception as e:
                                        logger.warning(f"处理内容字段时出错: {str(e)}")
                                        content = ''
                                
                                # 清理title和url中的特殊字符
                                title = ''.join(char for char in title if ord(char) >= 32 or char in '\n\r\t')
                                url = ''.join(char for char in url if ord(char) >= 32 or char in '\n\r\t')
                                
                                # 构建结果文本
                                result_text += f"{i}. {title}\n"
                                if url:
                                    result_text += f"   链接: {url}\n"
                                if content:
                                    result_text += f"   内容: {content}...\n"
                                result_text += "\n"
                                
                            except Exception as e:
                                # 单个结果处理失败不影响其他结果
                                logger.error(f"处理结果 {i} 时出错: {str(e)}", exc_info=True)
                                result_text += f"{i}. [处理此结果时出错，已跳过]\n\n"
                                continue
                    
                    print(f"🔍 DEBUG: 格式化结果长度: {len(result_text)} 字符")
                    # 直接返回格式化的文本字符串，qwen-agent工具期望返回字符串
                    return result_text
                else:
                    # 如果不是字典，转换为字符串返回
                    return str(data)
                    
            except json5.JSONDecodeError as json_err:
                logger.error(f"Tavily响应JSON解析失败: {str(json_err)}, 响应文本: {response.text[:200]}")
                return f'错误: 响应解析失败: {str(json_err)}。响应内容: {response.text[:200]}'
            
        except requests.HTTPError as http_err:
            status_code = http_err.response.status_code if http_err.response else '未知'
            error_detail = ''
            try:
                if http_err.response:
                    error_detail = http_err.response.text[:200]  # 只取前200字符
            except:
                pass
            logger.error(f"Tavily HTTP错误: 状态码={status_code}, 详情={error_detail}")
            return f'错误: Tavily请求失败，状态码: {status_code}。详情: {error_detail}'
        except requests.RequestException as req_err:
            logger.error(f"Tavily请求异常: {str(req_err)}")
            return f'错误: 网络请求失败: {str(req_err)}。请检查网络连接。'
        except json5.JSONDecodeError as json_err:
            logger.error(f"Tavily参数JSON解析失败: {str(json_err)}")
            return f'错误: 参数解析失败: {str(json_err)}'
        except Exception as e:
            logger.error(f"Tavily工具调用异常: {str(e)}", exc_info=True)
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"详细错误堆栈:\n{error_trace}")
            return f'错误: 调用Tavily失败: {str(e)}。请查看日志获取详细信息。'


def init_elasticsearch():
    """初始化Elasticsearch连接和索引"""
    global es_manager
    try:
        print("🔍 DEBUG: 开始初始化Elasticsearch连接")
        logger.info("=== 初始化Elasticsearch连接 ===")
        es_manager = ElasticsearchManager(
            es_host="localhost",  # 修改为您的ES地址
            es_port=9200,         # 修改为您的ES端口
            es_username="elastic",  # ES用户名
            es_password="rT_bpz*daxmw8rabCrp8"  # ES密码
        )
        print("🔍 DEBUG: Elasticsearch管理器创建成功")
        
        # 创建索引
        print("🔍 DEBUG: 开始创建索引")
        logger.info("=== 创建索引 ===")
        index_name = "insurance_docs"
        es_manager.create_index(index_name)
        print("🔍 DEBUG: 索引创建完成")
        
        # 索引文档
        print("🔍 DEBUG: 开始索引文档")
        logger.info("=== 索引文档 ===")
        docs_dir = "docs"
        es_manager.index_documents(docs_dir, index_name)
        print("🔍 DEBUG: 文档索引完成")
        
        # 获取索引信息
        doc_count = es_manager.get_index_info(index_name)
        logger.info(f"索引创建完成，包含 {doc_count} 个文档")
        print(f"🔍 DEBUG: 索引包含 {doc_count} 个文档")
        
        return True
        
    except Exception as e:
        print(f"❌ DEBUG: 初始化Elasticsearch失败: {str(e)}")
        logger.error(f"初始化Elasticsearch失败: {str(e)}")
        return False


def init_agent_service():
    """初始化助手服务"""
    # 步骤 3：配置您所使用的 LLM。
    llm_cfg = {
        # 使用 DashScope 提供的模型服务：
        'model': 'qwen-max',
        'model_server': 'dashscope',
        'api_key': os.getenv('DASHSCOPE_API_KEY'),  # 从环境变量获取API Key
        'generate_cfg': {
            'top_p': 0.8
        }
    }

    # 检查Tavily API Key - 多种方式尝试读取
    tavily_api_key = None
    
    # 方式1: 优先使用硬编码的API Key（如果设置了）
    if TAVILY_API_KEY_HARDCODED:
        tavily_api_key = TAVILY_API_KEY_HARDCODED
        print("ℹ️  使用硬编码的Tavily API Key（仅用于测试）")
    
    # 方式2: 从环境变量读取
    if not tavily_api_key:
        tavily_api_key = os.getenv('TAVILY_API_KEY')
    
    # 方式3: 尝试从os.environ直接读取
    if not tavily_api_key:
        tavily_api_key = os.environ.get('TAVILY_API_KEY')
    
    # 方式4: 尝试读取所有环境变量进行调试
    if not tavily_api_key:
        print("🔍 调试信息: 正在检查环境变量...")
        all_env_keys = [k for k in os.environ.keys() if 'TAVILY' in k.upper() or 'API' in k.upper()]
        if all_env_keys:
            print(f"   找到相关环境变量: {all_env_keys}")
        else:
            print("   未找到任何包含 'TAVILY' 或 'API' 的环境变量")
    
    if not tavily_api_key:
        print("⚠️  警告: 未检测到 TAVILY_API_KEY 环境变量")
        print("   网络搜索功能(tavily_mcp)将不可用，但本地文档搜索功能正常")
        print("   排查步骤:")
        print("   1. 确认环境变量已设置: 在PowerShell中运行 'echo $env:TAVILY_API_KEY'")
        print("   2. 如果显示为空，请重新设置: $env:TAVILY_API_KEY = \"your-api-key\"")
        print("   3. 如果已设置但仍检测不到，请重启IDE/终端后再试")
        print("   4. 临时方案: 在代码开头设置 TAVILY_API_KEY_HARDCODED = \"your-api-key\"")
        print("   获取API Key: https://app.tavily.com/home")
    else:
        print(f"✅ Tavily API Key 已配置 (前10位: {tavily_api_key[:10]}...)")
        print(f"   完整长度: {len(tavily_api_key)} 字符")

    # 步骤 4：创建一个智能体。这里我们以 `Assistant` 智能体为例，它能够使用工具并读取文件。
    system_instruction = '''你是保险文档搜索助手。对保险问题，必须先用 insurance_doc_search 工具搜索，然后基于结果回答。搜索类型默认 hybrid。
如果需要最新的网络信息，可以使用 tavily_mcp 工具进行实时搜索。'''
    
    # 优先配置保险文档搜索工具，确保被优先调用
    tools = ['insurance_doc_search', 'tavily_mcp', 'my_image_gen', 'code_interpreter']
    
    # 不加载文件，避免输入长度超限
    # 文件内容通过Elasticsearch搜索获取
    files = []
    print('🔍 DEBUG: 不加载文件，使用Elasticsearch搜索')

    bot = Assistant(llm=llm_cfg,
                    system_message=system_instruction,
                    function_list=tools,
                    files=files)
    
    print(f"🔍 DEBUG: 助手初始化完成")
    print(f"🔍 DEBUG: 可用工具: {tools}")
    print(f"🔍 DEBUG: 系统指令已设置")
    
    return bot


def app_tui():
    """终端交互模式
    
    提供命令行交互界面，支持：
    - 连续对话
    - 保险文档搜索
    - 实时响应
    """
    try:
        # 初始化Elasticsearch
        if not init_elasticsearch():
            print("Elasticsearch初始化失败，程序退出")
            return
        
        # 初始化助手
        bot = init_agent_service()

        # 对话历史
        messages = []
        print("保险文档搜索终端交互模式已启动，输入 'quit' 或 'exit' 退出")
        print("您可以询问任何保险相关的问题，如：雇主责任险的保障范围、财产险的理赔流程等")
        
        while True:
            try:
                # 获取用户输入
                query = input('\n用户问题: ').strip()
                
                # 检查退出命令
                if query.lower() in ['quit', 'exit', '退出']:
                    print("再见！")
                    break
                
                # 输入验证
                if not query:
                    print('用户问题不能为空！')
                    continue
                    
                # 构建消息
                messages.append({'role': 'user', 'content': query})

                print("正在搜索相关保险文档...")
                # 运行助手并处理响应
                response = []
                current_index = 0
                first_chunk = True
                for response_chunk in bot.run(messages=messages):
                    if first_chunk:
                        # 尝试获取并打印召回的文档内容
                        if hasattr(bot, 'retriever') and bot.retriever:
                            print("\n===== 召回的文档内容 =====")
                            retrieved_docs = bot.retriever.retrieve(query)
                            if retrieved_docs:
                                for i, doc in enumerate(retrieved_docs):
                                    print(f"\n文档片段 {i+1}:")
                                    print(f"内容: {doc.page_content}")
                                    print(f"元数据: {doc.metadata}")
                            else:
                                print("没有召回任何文档内容")
                            print("===========================\n")
                        first_chunk = False

                    # The response is a list of messages. We are interested in the assistant's message.
                    if response_chunk and response_chunk[0]['role'] == 'assistant':
                        assistant_message = response_chunk[0]
                        new_content = assistant_message.get('content', '')
                        print(new_content[current_index:], end='', flush=True)
                        current_index = len(new_content)
                    
                    response = response_chunk
                
                print() # New line after streaming.

                messages.extend(response)
            except KeyboardInterrupt:
                print("\n\n程序被用户中断，再见！")
                break
            except EOFError:
                print("\n\n输入流结束，程序退出")
                break
            except Exception as e:
                print(f"处理请求时出错: {str(e)}")
                print("请重试或输入新的问题")
    except Exception as e:
        print(f"启动终端模式失败: {str(e)}")


def app_gui():
    """图形界面模式，提供 Web 图形界面"""
    try:
        print("正在启动 Web 界面...")
        
        # 初始化Elasticsearch
        if not init_elasticsearch():
            print("Elasticsearch初始化失败，程序退出")
            return
        
        # 初始化助手
        bot = init_agent_service()
        
        # 配置聊天界面，列举保险相关的典型查询问题
        chatbot_config = {
            'prompt.suggestions': [
                '雇主责任险的保障范围是什么？',
                '财产一切险包含哪些保障内容？',
                '平安企业团体综合意外险的理赔流程',
                '雇主安心保的保险责任有哪些？',
                '施工保的保障范围包括什么？',
                '平安装修保的保险条款',
                '保险理赔需要哪些材料？',
                '保险费的缴纳方式有哪些？'
            ]
        }
        print("Web 界面准备就绪，正在启动服务...")
        print("访问地址: http://localhost:7860")
        print("现在您可以询问任何保险相关的问题！")
        
        # 启动 Web 界面
        WebUI(
            bot,
            chatbot_config=chatbot_config
        ).run()
    except Exception as e:
        print(f"启动 Web 界面失败: {str(e)}")
        print("请检查网络连接和 API Key 配置")


if __name__ == '__main__':
    import sys
    
    # 运行模式选择
    if len(sys.argv) > 1 and sys.argv[1] == '--tui':
        print("启动终端交互模式...")
        app_tui()
    else:
        print("启动图形界面模式...")
        print("如需启动终端模式，请使用: python integrated_insurance_search.py --tui")
        app_gui()
