<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:atom="http://www.w3.org/2005/Atom"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <xsl:output method="html" encoding="UTF-8" indent="yes" />
  <xsl:template match="/">
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>
          <xsl:choose>
            <xsl:when test="/rss/channel/title">
              <xsl:value-of select="/rss/channel/title" /> &#8212; Feed
            </xsl:when>
            <xsl:when test="/atom:feed/atom:title">
              <xsl:value-of select="/atom:feed/atom:title" /> &#8212; Feed
            </xsl:when>
            <xsl:otherwise>RSS Feed</xsl:otherwise>
          </xsl:choose>
        </title>
        <style>
          *,*::before,*::after{box-sizing:border-box}
          body{
            font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen-Sans,Ubuntu,Cantarell,"Helvetica Neue",sans-serif;
            max-width:42rem;margin:0 auto;padding:2rem 1rem;
            color:#1a1a1a;background:#fff;line-height:1.6;
          }
          .banner{
            background:#f0f4f8;border:1px solid #d0d7de;border-radius:8px;
            padding:1rem 1.25rem;margin-bottom:2rem;
          }
          .banner p{margin:0;font-size:0.9rem;color:#57606a}
          .banner a{color:#0969da}
          h1{font-size:1.75rem;margin:0 0 0.25rem;letter-spacing:-0.025em}
          .description{color:#57606a;margin:0 0 2rem}
          .item{border-bottom:1px solid #d8dee4;padding:1rem 0}
          .item:last-child{border-bottom:none}
          .item-title{font-size:1.1rem;font-weight:600;margin:0 0 0.25rem}
          .item-title a{color:#1a1a1a;text-decoration:none}
          .item-title a:hover{color:#0969da}
          .item-meta{font-size:0.85rem;color:#57606a;margin:0 0 0.5rem}
          .item-summary{font-size:0.95rem;color:#444;margin:0}
        </style>
      </head>
      <body>
        <div class="banner">
          <p><strong>This is an RSS feed.</strong> Copy this URL into your feed reader to subscribe.
          Visit <a href="https://aboutfeeds.com">aboutfeeds.com</a> to learn more about RSS.</p>
        </div>

        <!-- RSS 2.0 -->
        <xsl:if test="/rss/channel">
          <h1><xsl:value-of select="/rss/channel/title" /></h1>
          <p class="description"><xsl:value-of select="/rss/channel/description" /></p>
          <xsl:for-each select="/rss/channel/item">
            <div class="item">
              <p class="item-title">
                <a>
                  <xsl:attribute name="href"><xsl:value-of select="link" /></xsl:attribute>
                  <xsl:value-of select="title" />
                </a>
              </p>
              <p class="item-meta"><xsl:value-of select="pubDate" /></p>
              <xsl:if test="description">
                <p class="item-summary"><xsl:value-of select="description" disable-output-escaping="yes" /></p>
              </xsl:if>
            </div>
          </xsl:for-each>
        </xsl:if>

        <!-- Atom -->
        <xsl:if test="/atom:feed">
          <h1><xsl:value-of select="/atom:feed/atom:title" /></h1>
          <p class="description"><xsl:value-of select="/atom:feed/atom:subtitle" /></p>
          <xsl:for-each select="/atom:feed/atom:entry">
            <div class="item">
              <p class="item-title">
                <a>
                  <xsl:attribute name="href"><xsl:value-of select="atom:link[@rel='alternate']/@href" /></xsl:attribute>
                  <xsl:value-of select="atom:title" />
                </a>
              </p>
              <p class="item-meta"><xsl:value-of select="atom:updated" /></p>
              <xsl:if test="atom:summary">
                <p class="item-summary"><xsl:value-of select="atom:summary" disable-output-escaping="yes" /></p>
              </xsl:if>
            </div>
          </xsl:for-each>
        </xsl:if>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
