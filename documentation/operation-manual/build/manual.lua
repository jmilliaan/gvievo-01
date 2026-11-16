-- Pandoc filter for the operation manual PDF.
-- Block quotes become boxes: "**⚠ WARNING/CAUTION/DANGER …**" → safety box, "**[REVIEW]**" → grey review box,
-- the "**DRAFT …**" banner → draft box. Code spans that start with "[" are placeholders (yellow).

local function first_strong(bq)
  local b = bq.content[1]
  if b and (b.t == 'Para' or b.t == 'Plain') then
    for _, il in ipairs(b.content) do
      if il.t == 'Strong' then return pandoc.utils.stringify(il) end
      if il.t ~= 'Space' then break end
    end
  end
  return ''
end

function BlockQuote(bq)
  local s = first_strong(bq)
  local cls = 'note'
  if s:find('^%[REVIEW%]') then cls = 'review'
  elseif s:find('DANGER') then cls = 'safety danger'
  elseif s:find('WARNING') then cls = 'safety warning'
  elseif s:find('CAUTION') then cls = 'safety caution'
  elseif s:find('^DRAFT') then cls = 'draft' end
  -- keep a bold title on its own line: the first soft line break after it becomes a hard one
  local b = bq.content[1]
  if s ~= '' and cls ~= 'review' then
    for i, il in ipairs(b.content) do
      if il.t == 'SoftBreak' then b.content[i] = pandoc.LineBreak(); break end
    end
  end
  return pandoc.Div(bq.content, pandoc.Attr('', { 'box', table.unpack(pandoc.List(cls:gmatch('%S+'))) }))
end

function Code(c)
  if c.text:sub(1, 1) == '[' then c.classes:insert('ph') end
  return c
end
