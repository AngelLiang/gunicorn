# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import urlparse

from gunicorn.util import normalize_name

class HttpParserError(Exception):
    """ error raised when parsing fail"""

class HttpParser(object):
    
    def __init__(self):
        self.status = ""                # 状态
        self.headers = []               # HTTP头部 type: list
        self.headers_dict = {}          # HTTP头部 type: dict
        self.raw_version = "HTTP/1.0"   # HTTP版本 type: str
        self.raw_path = ""
        self.version = (1,0)            # HTTP版本 type: tuple
        self.method = ""
        self.path = ""
        self.query_string = ""
        self.fragment = ""
        self._content_len = None
        self.start_offset = 0
        self.chunk_size = 0
        self._chunk_eof = False      
        
    def filter_headers(self, headers, buf):
        """ take a string as buffer and an header dict 
        (empty or not). It return new position or -1 
        if parsing isn't done. headers dict is updated
        with new headers.
        """
        if self.headers:
            return self.headers
        
        # 检查"\r\n\r\n"，不存在则返回-1
        ld = len("\r\n\r\n")
        i = buf.find("\r\n\r\n")
        if i != -1:
            if i > 0:
                r = buf[:i]
            pos = i+ld  # 定位
            return self.finalize_headers(headers, r, pos)
        return -1
        
    def finalize_headers(self, headers, headers_str, pos):
        """ parse the headers """

        # 把 HTTP request 用 "\r\n" 切割成list
        lines = headers_str.split("\r\n")
                
        # parse first line of headers
        # 获取请求行
        self._first_line(lines.pop(0))
        
        # parse headers. We silently ignore 
        # bad headers' lines
        
        # 获取请求头，并转换为字典
        _headers = {}
        hname = ""
        for line in lines:
            if line == "\t":
                headers[hname] += line.strip()
            else:
                try:
                    hname =self._parse_headerl(_headers, line)
                except ValueError: 
                    # bad headers
                    pass
        self.headers_dict = _headers
        headers.extend(list(_headers.items()))
        self.headers = headers
        # 提取长度变量，单独存放
        self._content_len = int(_headers.get('Content-Length',0))
        (_, _, self.path, self.query_string, self.fragment) = urlparse.urlsplit(self.raw_path)
        return pos
    
    def _first_line(self, line):
        """ parse first line """
        """
        解析HTTP请求行，比如
        ```
        GET /hello HTTP/1.0
        ```
        """
        self.status = status = line.strip()
        
        method, path, version = status.split(" ")   # 获取方法、路径和HTTP版本
        version = version.strip()
        self.raw_version = version
        try:
            major, minor = version.split("HTTP/")[1].split(".")
            version = (int(major), int(minor))
        except IndexError:
            version = (1, 0)

        self.version = version
        self.method = method.upper()    # method转换为大写字母
        self.raw_path = path
        
    def _parse_headerl(self, hdrs, line):
        """ parse header line"""
        name, value = line.split(":", 1)
        name = normalize_name(name.strip())
        hdrs[name] = value.rsplit("\r\n",1)[0].strip()
        return name
      
    @property
    def should_close(self):
        """
        通过检查 self.headers_dict:dict 来判断是否需要close
        """
        if self._should_close:
            return True
        if self.headers_dict.get("Connection") == "close":
            return True
        if self.headers_dict.get("Connection") == "Keep-Alive":
            return False
        if int("%s%s" % self.version) < 11:
            return True
        
    @property
    def is_chunked(self):
        """ is TE: chunked ?"""
        transfert_encoding = self.headers_dict.get('Transfer-Encoding', False)
        return (transfert_encoding == "chunked")
        
    @property
    def content_len(self):
        """ return content length as integer or
        None."""
        transfert_encoding = self.headers_dict.get('Transfer-Encoding')
        content_length = self.headers_dict.get('Content-Length')
        if transfert_encoding != "chunked":
            if content_length is None:
                return 0
            return int(content_length)
        else:
            return None
            
    def body_eof(self):
        """do we have all the body ?"""
        if self.is_chunked:
            if self._chunk_eof:
                return True
        elif self._content_len == 0:
                return True
        return False
        
    def read_chunk(self, data):
        if not self.start_offset:
            i = data.find("\r\n")
            if i != -1:
                chunk = data[:i].strip().split(";", 1)
                chunk_size = int(chunk.pop(0), 16)
                self.start_offset = i+2
                self.chunk_size = chunk_size
                if self.chunk_size == 0:
                    self._chunk_eof = True
                    return '', data[:self.start_offset]
        else:
            buf = data[self.start_offset:self.start_offset+self.chunk_size]
            end_offset = self.start_offset + self.chunk_size + 2
            # we wait CRLF else return None
            if len(data) >= end_offset:
                ret = buf, data[end_offset:]
                self.chunk_size = 0
                return ret
        return '', data
        
    def trailing_header(self, data):
        i = data.find("\r\n\r\n")
        return (i != -1)
        
    def filter_body(self, data):
        """ filter body and return a tuple:
        body_chunk, new_buffer. They could be None.
        new_fubber is always None if it's empty.
        
        """
        dlen = len(data)
        chunk = ''
        if self.is_chunked:

            chunk, data = self.read_chunk(data)
            
            if not chunk:
                return '', data
        else:
            if self._content_len > 0:
                nr = min(dlen, self._content_len)
                chunk = data[:nr]
                self._content_len -= nr
                data = ''
                
        self.start_offset = 0
        return (chunk, data)
